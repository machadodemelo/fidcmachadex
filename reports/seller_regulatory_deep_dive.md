# Estudo Seller — emissões, pagamentos e critérios monitoráveis por IME

Data da revisão: 2026-05-10

## Escopo

Fundos analisados:

| Fundo | CNPJ | Base documental local |
| --- | --- | --- |
| SELLER FIDC Segmento Meios de Pagamento | 50.473.039/0001-02 | 44 documentos inventariados; 21 PDFs institucionais baixados |
| SELLER II FIDC Segmento Meios de Pagamento | 55.471.753/0001-77 | 28 documentos inventariados; 13 PDFs institucionais baixados |
| SELLER 3 FIDC Segmento Meios de Pagamento | 63.572.282/0001-11 | 10 documentos inventariados; 10 PDFs institucionais baixados |

Arquivos gerados:

- `reports/seller_document_inventory.csv`: inventário CVM/FNET filtrado para os três Sellers.
- `reports/seller_cotas_emissoes_pagamentos.csv`: linha do tempo de cotas, datas, volumes, remuneração e amortização.
- `reports/seller_criteria_monitoraveis_ime.csv`: matriz de critérios que podem ser acompanhados direta ou parcialmente por dados do Informe Mensal Estruturado.

A leitura foi feita com os PDFs locais em `data/raw/<cnpj>/` e com a base estruturada em `data/regulatory_knowledge/<cnpj>.json`. Não foi feita chamada externa de LLM.

## Conclusões principais

1. **SELLER original tem calendário completo para as séries sênior 1, 2 e 5.** As séries 3 e 4 aparecem aprovadas e ofertadas, mas os PDFs baixados não trazem o suplemento específico com spread e cronograma de amortização.
2. **SELLER II tem calendário completo para a sênior 1ª série.** A amortização é mensal em seis parcelas de 1/6 do VNU entre 15/02/2027 e 15/07/2027; a remuneração é mensal, sem carência.
3. **SELLER 3 tem calendário completo para a sênior 1ª série.** A primeira integralização é 05/02/2026; amortização programada de 15/09/2028 a 15/02/2029; juros semestrais.
4. **Subordinação mínima vigente:** SELLER = 10%; SELLER II = 33,3%; SELLER 3 = 10%. No caso de SELLER II, a leitura heurística anterior capturava “3,3%”; a página 106 do regulamento consolidado mostra “33,3%”.
5. **Os critérios mais úteis para monitoramento por IME são:** subordinação, alocação em direitos creditórios, ausência de derivativos, PL mínimo (SELLER II) e proxies de reserva/caixa. Índices de cobertura e reserva de caixa dependem de inputs manuais para virarem alerta confiável.
6. **Não recomendo criar alerta automático para “inadimplemento de direitos creditórios por mais de 5 dias”.** O IME mensal pode mostrar Over 1d ou buckets de atraso, mas a regra do regulamento é diária e por direito creditório.

## Documentos-chave por fundo

### SELLER — 50.473.039/0001-02

Regulamento vigente usado para critérios: `909547_regulamento_regulamento_909547_2025-05-19.pdf`.

Documentos de emissão/pagamento relevantes:

| Documento | Data | Uso na análise |
| --- | --- | --- |
| `467929_regulamento...2023-05-05.pdf` | 05/05/2023 | Suplementos das séries sênior 1 e 2, com spread e amortização |
| `468755_assembleia...2023-05-22.pdf` | 22/05/2023 | Aprovação das séries sênior 1 e 2 |
| `471622_emissao...2023-05-30.pdf` | 30/05/2023 | Ajusta a Data de Liquidação para 31/05/2023 |
| `558803_assembleia...2023-11-23.pdf` | 23/11/2023 | Aprova sênior 3, sênior 4 e junior privada |
| `559856_emissao...2023-11-27.pdf` | 27/11/2023 | Anúncio de início das séries 3 e 4 |
| `909546_assembleia...2025-05-19.pdf` | 19/05/2025 | Aprova alteração regulamento e sênior 5 |
| `912093_assembleia...2025-05-26.pdf` | 26/05/2025 | Instrumento da sênior 5, com spread e amortização |
| `912172_emissao...2025-05-28.pdf` | 28/05/2025 | Anúncio de início; primeira integralização em 29/05/2025 |
| `932137_emissao...2025-06-04.pdf` | 04/06/2025 | Encerramento da oferta da sênior 5 |

#### Cotas identificadas

| Cota | Data de emissão / 1ª integralização | Volume | Remuneração | Juros | Amortização |
| --- | --- | ---: | --- | --- | --- |
| Sênior 1ª série | 31/05/2023 | R$ 1,0 bi | DI + 1,60% a.a. | Semestral desde o 6º mês | 15/12/2025 25%; 15/01/2026 33,33%; 15/02/2026 50%; 15/03/2026 100% |
| Sênior 2ª série | 31/05/2023 | R$ 0,5 bi | DI + 1,80% a.a. | Semestral desde o 6º mês | 15/04/2026 50%; 15/05/2026 100% |
| Sênior 3ª série | Não identificada | R$ 200 mm | Não identificada | Não identificado | Não identificado |
| Sênior 4ª série | Não identificada | R$ 100 mm | Não identificada | Não identificado | Não identificado |
| Subordinada Júnior 2023 | Não identificada | R$ 200 mm | Residual / sem parâmetro | Sem calendário fixo | Sem calendário fixo |
| Sênior 5ª série | 29/05/2025 | R$ 1,5 bi | DI + 0,85% a.a. | Semestral desde o 6º mês | 15/12/2027 16,67%; 15/01/2028 20%; 15/02/2028 25%; 15/03/2028 33,33%; 15/04/2028 50%; 15/05/2028 100% |

### SELLER II — 55.471.753/0001-77

Regulamento-base usado para critérios: `704724_regulamento_regulamento_704724_2024-07-25.pdf`.
Aditivo mais recente usado para a sênior 1ª série: `705139_regulamento_regulamento_705139_2024-07-26.pdf`.

Documentos relevantes:

| Documento | Data | Uso na análise |
| --- | --- | --- |
| `691281_assembleia...2024-06-10.pdf` | 10/06/2024 | Constituição e emissão inicial de subordinadas junior |
| `704724_regulamento...2024-07-25.pdf` | 25/07/2024 | Regulamento consolidado e critérios vigentes de base |
| `705139_regulamento...2024-07-26.pdf` | 26/07/2024 | Aditivo da sênior 1ª série com spread/fator/rating |
| `705145_evento...2024-07-26.pdf` | 26/07/2024 | Bookbuilding: sobretaxa sênior 0,85% a.a. |
| `706203_emissao...2024-07-29.pdf` | 29/07/2024 | Anúncio de início da sênior 1ª série |
| `714216_emissao...2024-08-08.pdf` | 08/08/2024 | Encerramento em 06/08/2024; 1.000.000 cotas subscritas |
| `733048_assembleia...2024-09-06.pdf` | 06/09/2024 | Emissão adicional de subordinadas junior |

#### Cotas identificadas

| Cota | Data de emissão / 1ª integralização | Volume | Remuneração | Juros | Amortização |
| --- | --- | ---: | --- | --- | --- |
| Subordinada Júnior inicial | Não identificada | Até R$ 50 mm | Residual / sem parâmetro | Sem calendário fixo | Sem calendário fixo |
| Sênior 1ª série | Não textual; oferta encerrada em 06/08/2024 | R$ 1,0 bi | DI + 0,85% a.a. | Mensal, sem carência | 15/02/2027 a 15/07/2027, 1/6 do VNU por mês |
| Subordinada Júnior adicional | Não identificada | Até 10.000 cotas; volume depende do VNU | Residual / sem parâmetro | Sem calendário fixo | Sem calendário fixo |

### SELLER 3 — 63.572.282/0001-11

Regulamento vigente usado para critérios: `1089845_regulamento_regulamento_1089845_2026-01-21.pdf`.

Documentos relevantes:

| Documento | Data | Uso na análise |
| --- | --- | --- |
| `1059049_assembleia...2025-11-07.pdf` | 07/11/2025 | Constituição da classe com sênior, mezanino e junior |
| `1080485_regulamento...2026-01-05.pdf` | 05/01/2026 | Emissão privada de 2.000 cotas junior |
| `1080490_assembleia...2026-01-12.pdf` | 12/01/2026 | 2ª emissão junior de R$ 16 mm |
| `1089840_assembleia...2026-01-21.pdf` | 21/01/2026 | Aprova sênior 1ª série e 3ª emissão junior |
| `1089845_regulamento...2026-01-21.pdf` | 21/01/2026 | Regulamento vigente e apêndice da sênior 1ª série |
| `1101975_emissao...2026-02-04.pdf` | 04/02/2026 | Anúncio de início; primeira integralização em 05/02/2026 |
| `1104314_emissao...2026-02-06.pdf` | 06/02/2026 | Encerramento da sênior 1ª série |

Observação: o inventário tem `1091930_emissao...2025-01-23.pdf`, entregue em 26/01/2026, com data de referência anterior à constituição. Tratei como documento com data inconsistente para a linha do tempo do Seller 3; usei os documentos de 2026 para a cronologia econômica.

#### Cotas identificadas

| Cota | Data de emissão / 1ª integralização | Volume | Remuneração | Juros | Amortização |
| --- | --- | ---: | --- | --- | --- |
| Subordinada Júnior aprovada em 05/01/2026 | Não identificada | R$ 2 mm | Residual / sem parâmetro | Sem calendário fixo | Sem calendário fixo |
| Subordinada Júnior 2ª emissão | 12/01/2026 | R$ 16 mm | Residual / sem parâmetro | Sem calendário fixo | Sem calendário fixo |
| Sênior 1ª série | 05/02/2026 | R$ 1,5 bi | DI + 0,65% a.a. | Semestral desde o 6º mês | 15/09/2028 16,6667%; 15/10/2028 20%; 15/11/2028 25%; 15/12/2028 33,3333%; 15/01/2029 50%; 15/02/2029 100% |
| Subordinada Júnior 3ª emissão | Não identificada | Até R$ 195 mm | Residual / sem parâmetro | Sem calendário fixo | Sem calendário fixo |

## Critérios monitoráveis pelo Informe Mensal Estruturado

### Monitoramento direto, com validação metodológica

| Critério | SELLER | SELLER II | SELLER 3 | Métrica IME sugerida | Ressalva |
| --- | ---: | ---: | ---: | --- | --- |
| Subordinação mínima junior/PL | 10% | 33,3% | 10% | Cotas Subordinadas Juniores / PL; usar Cotas Sub / PL apenas quando não houver mezanino | Confirmar classificação das classes no XML para não somar mezanino indevidamente |
| Alocação mínima regulatória | 50% | 50% | 50% | Direitos Creditórios / PL | IME não prova elegibilidade individual dos créditos |
| Alocação mínima tributária/adicional | 67% | 67% | 67% | Direitos Creditórios / PL | Texto dos regulamentos mostra “67%” com extenso “cinquenta por cento”; validar juridicamente |
| Derivativos vedados | Zero | Zero | Zero | Posições mantidas em derivativos | IME é agregado, mas a vedação total permite alerta se houver posição não-zero |
| PL mínimo | Não identificado como regra específica | R$ 1 mm por 90 dias consecutivos | Não identificado como regra específica | PL | IME é mensal; serve como triagem, não como prova diária |

### Monitoramento parcial; exige parâmetros manuais

| Critério | Regra | Por que não é 100% IME | Como operacionalizar sem fingir precisão |
| --- | --- | --- | --- |
| Índice de Cobertura Sênior | Índice >= 1,00 | Fórmula usa Valor Presente dos DCs, Disponibilidades, Comissões e Fator de Ponderação por série | Cadastrar fator por série e calcular proxy; alertar como “proxy de cobertura”, não covenant final |
| Índice de Cobertura Mezanino | Índice >= 1,00 quando houver mezanino | Mesma limitação do índice sênior | Só ativar quando houver mezanino emitido e fator cadastrado |
| Reserva de Liquidez | 3 meses de despesas ordinárias | IME não fornece a base contratual de despesas ordinárias projetadas | Cadastrar despesa mensal de referência; comparar com disponibilidades/ativos financeiros |
| Reserva de Caixa | 100% do próximo pagamento; Seller/Seller 3 acumulam de D-45 a D-10; Seller II separa principal e remuneração | Exige saldo vivo, remuneração acumulada e calendário de pagamento | Usar o calendário extraído + saldo de cotas + curva CDI para projeção; sinalizar “parcial” |
| Inadimplemento >5 dias de qualquer direito creditório | Evento de liquidação nos regulamentos Seller/Seller 3 e estrutura similar | Regra é diária e por título; IME é mensal e agregado por bucket | Usar Over 1d apenas como sinal qualitativo; não como gatilho automático |

### Não monitorável por IME público

| Critério | Motivo |
| --- | --- |
| Inconsistência de documentação/lastro acima de 5% da amostra | Depende de auditoria de documentos comprobatórios e amostras, não aparece no IME |
| Alterações societárias, rating, licenças, contratos, falência/RAET, cessões externas do Mercado Pago | Depende de documentos societários, ratings ou eventos operacionais externos |
| Critérios de elegibilidade granular por direito creditório | IME não traz carteira granular nem teste individual de elegibilidade |
| Estoque Livre do Devedor | Não é campo padronizado do IME |

## Recomendação para a próxima etapa do app

1. Criar uma tabela manual por fundo/série com: subordinação mínima, fatores de ponderação, calendário de amortização/juros, despesas ordinárias mensais e status de série viva.
2. Calcular no app apenas três grupos de alertas de primeira versão:
   - Subordinação junior/PL.
   - Alocação em direitos creditórios/PL.
   - Derivativos vedados.
3. Exibir os demais como “proxies operacionais” até que os inputs manuais estejam completos:
   - Índice de cobertura.
   - Reserva de caixa.
   - Reserva de liquidez.
4. Não transformar inadimplência >5 dias em alerta vermelho automático com base no IME. O IME pode indicar risco, mas não fecha o gatilho jurídico.

## Limitações e pontos de auditoria

- A extração textual de PDFs não substitui leitura jurídica final; preservei arquivo e página de origem para cada ponto material.
- As séries 3 e 4 do SELLER original aparecem em atas/anúncios, mas o cronograma de juros/amortização não foi encontrado nos PDFs baixados. Se houver suplemento fora do pacote local, ele deve ser anexado antes de completar o calendário.
- SELLER II usa o regulamento consolidado de 25/07/2024 para critérios gerais e o aditivo de 26/07/2024 para a sênior 1ª série. O aditivo não substitui sozinho todo o regulamento-base.
- O documento `1091930` do SELLER 3 tem data de referência 23/01/2025, mas foi entregue em 26/01/2026 e se refere à oferta da sênior; não usei essa data como data econômica de emissão.
