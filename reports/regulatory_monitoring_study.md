# Estudo regulatório dos FIDCs monitorados

Gerado em: 2026-05-10T03:20:41Z

## Resumo executivo

- Fundos com base gerada: 36
- Documentos inventariados: 1500
- Documentos com extração estruturada: 728
- Critérios extraídos: 2389
- Critérios classificados como monitoráveis pelo IME: 1366
- Documentos com erro de extração estruturada: 24

A base separa documentos, critérios regulatórios e eventos de emissão/amortização. O app deve monitorar apenas critérios explicitamente encontrados e com mapeamento viável para o Informe Mensal; os demais ficam como referência para análise manual.

A extração estruturada desta entrega foi feita localmente, sem chamada externa de LLM: o script extrai texto dos PDFs e aplica regras heurísticas auditáveis. Cada critério candidato preserva trecho-fonte e deve ser validado pelo analista antes de virar alerta automático.

## Critérios mais recorrentes e monitorabilidade

| Critério | Ocorrências | Fundos | Monitoramento | Métrica IME |
| --- | --- | --- | --- | --- |
| credit_rights_allocation_min | 741 | 36 | monitoravel | Dir Cred / PL |
| permitted_hedges | 532 | 29 | parcial | Posições mantidas em derivativos |
| concentration_limits | 178 | 26 | nao_monitoravel |  |
| subordination_ratio_min | 374 | 24 | monitoravel | Cotas Sub / PL %, Cotas MZ / PL % e Cotas SR / PL % |
| minimum_cash_ratio | 309 | 17 | parcial | Disponibilidades / PL ou Disponibilidades / amortização estimada |
| pdd_coverage_min | 141 | 15 | monitoravel | PDD / Venc Total ou PDD / Venc > 90 d |
| default_rate_evaluation_event | 75 | 9 | monitoravel | Vencidos Over 30/60/90/180/360 d / Crédito |
| recompras_max | 29 | 7 | monitoravel | Recompras / Crédito ou Recompras / PL |
| default_rate_early_maturity | 6 | 1 | monitoravel | Vencidos Over 30/60/90/180/360 d / Crédito |
| dilution_rate_max | 4 | 1 | nao_monitoravel |  |

## Cobertura por fundo

| Fundo | CNPJ | Documentos | Regulamentos | Assembleias | Emissões | Critérios | Monitoráveis | Parciais | Último doc. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CRÉDITO UNIVERSITÁRIO FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS - RESPONSABILIDADE LIMITADA | 08.417.544/0001-65 | 112 | 3 | 25 | 13 | 135 | 54 | 81 | 31/12/2025 |
| CARTÃO DE COMPRA SUPPLIER FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS - RESPONSABILIDADE LIMITADA | 08.692.888/0001-82 | 79 | 6 | 24 | 3 | 106 | 72 | 29 | 31/12/2025 |
| PRAVALER CRÉDITO UNIVERSITÁRIO II FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS - RESP LIMITADAL | 26.749.095/0001-34 | 80 | 8 | 16 | 9 | 126 | 38 | 78 | 31/12/2025 |
| FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS PAGSEGURO I | 28.169.275/0001-72 | 71 | 6 | 10 | 3 | 111 | 48 | 45 | 31/12/2025 |
| Mercado Crédito Merchant Fundo de Investimento em Direitos Creditórios | 28.472.333/0001-32 | 52 | 3 | 10 | 0 | 22 | 15 | 7 | 31/12/2023 |
| MERCADO CRÉDITO FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS RESPONSABILIDADE LIMITADA | 33.254.370/0001-04 | 75 | 13 | 16 | 0 | 89 | 61 | 27 | 31/12/2025 |
| CREDITO UNIVERSITARIO III FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS - RESPONSABILIDADE LIMITADA | 34.408.539/0001-04 | 64 | 13 | 22 | 0 | 190 | 58 | 116 | 31/12/2025 |
| FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS BV - CRÉDITO DE VEÍCULOS RESPONSABILIDADE LIMITADA | 35.868.110/0001-54 | 52 | 10 | 13 | 1 | 51 | 20 | 21 | 31/12/2024 |
| MERCADO CRÉDITO I BRASIL FIDC SEGMENTO FINANCEIRO DE RESPONSABILIDADE LIMITADA | 37.511.828/0001-14 | 73 | 12 | 26 | 0 | 169 | 124 | 28 | 31/12/2025 |
| MERCADO CRÉDITO II BRASIL FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS DE RESPONSABILIDADE LIMITADA | 41.970.012/0001-26 | 78 | 22 | 15 | 2 | 171 | 164 | 6 | 31/12/2025 |
| CLOUDWALK KICK ASS I FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 42.085.816/0001-05 | 52 | 11 | 7 | 0 | 43 | 29 | 7 | 31/12/2025 |
| CLOUDWALK AKIRA I FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 42.085.830/0001-09 | 41 | 9 | 4 | 0 | 35 | 17 | 14 | 31/12/2024 |
| CLOUDWALK KICK ASS II FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 42.102.603/0001-44 | 50 | 13 | 8 | 1 | 64 | 39 | 10 | 31/12/2023 |
| CLOUDWALK AKIRA II FIDC SEGMENTO MEIOS DE PAGAMENTO | 44.124.617/0001-94 | 47 | 10 | 6 | 0 | 52 | 30 | 14 | 31/12/2025 |
| SUMUP SOLO FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO DE RESPONSABILI | 45.598.747/0001-21 | 40 | 9 | 2 | 2 | 21 | 3 | 12 | 31/12/2025 |
| SELLER FIDC SEGMENTO MEIOS DE PAGAMENTO DE RESPONSABILIDADE LIMITADA | 50.473.039/0001-02 | 44 | 8 | 6 | 7 | 75 | 48 | 23 | 31/03/2025 |
| CARTÃO DE COMPRA SUPPLIER FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS II-RESPONSABILIDADE LIMITADA | 50.988.212/0001-05 | 40 | 7 | 17 | 2 | 53 | 34 | 19 | 31/12/2025 |
| FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS ANGÁ FGTS I - RESPONSABILIDADE LIMITADA | 51.957.370/0001-52 | 44 | 10 | 12 | 5 | 144 | 86 | 58 | 30/09/2025 |
| CLOUDWALK BIG PICTURE I FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 54.218.673/0001-41 | 28 | 6 | 2 | 5 | 21 | 6 | 10 | 31/12/2025 |
| CLOUDWALK BIG PICTURE II FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 54.218.941/0001-25 | 27 | 6 | 2 | 5 | 21 | 6 | 10 | 31/12/2025 |
| CLOUDWALK BIG PICTURE III FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 54.219.179/0001-00 | 28 | 6 | 2 | 5 | 25 | 10 | 10 | 31/12/2025 |
| CLOUDWALK BIG PICTURE IV FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 54.248.022/0001-02 | 29 | 6 | 2 | 5 | 31 | 16 | 10 | 31/12/2025 |
| ESTRATÉGIA VINCULADA I FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS - RESPONSABILIDADE LIMITADA | 54.559.035/0001-94 | 17 | 2 | 3 | 2 | 6 | 6 | 0 | 31/05/2025 |
| ANGÁ FGTS III FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS | 54.810.968/0001-02 | 25 | 6 | 8 | 2 | 87 | 48 | 39 | 30/11/2025 |
| ESTRATÉGIA VINCULADA II FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS - RESPONSABILIDADE LIMITADA | 55.070.804/0001-59 | 14 | 1 | 2 | 2 | 2 | 2 | 0 | 31/05/2025 |
| QUATÁ FDC FGTS FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS | 55.401.645/0001-28 | 33 | 11 | 6 | 5 | 142 | 110 | 30 | 30/04/2025 |
| SELLER II FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO RESP LTDA | 55.471.753/0001-77 | 28 | 5 | 3 | 2 | 37 | 22 | 15 | 31/03/2025 |
| CRÉDITO UNIVERSITÁRIO IV FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS - RESPONSABILIDADE LIMITADA | 55.983.705/0001-68 | 34 | 5 | 7 | 7 | 79 | 37 | 42 | 31/12/2025 |
| CLOUDWALK A.I. FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 57.609.282/0001-46 | 26 | 8 | 5 | 1 | 20 | 12 | 2 | 31/12/2025 |
| CLOUDWALK PI FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 60.356.171/0001-80 | 16 | 3 | 3 | 3 | 22 | 14 | 2 | 31/12/2025 |
| CLOUDWALK BELA FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO | 62.393.679/0001-83 | 35 | 9 | 10 | 6 | 61 | 37 | 15 | 31/12/2025 |
| VTK FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS RESPONSABILIDADE LIMITADA | 62.588.266/0001-54 | 13 | 4 | 3 | 3 | 59 | 39 | 16 | 31/12/2025 |
| SUMUP SMART IV FIDC SEGMENTO MEIOS DE PAGAMENTO DE RESPONSABILIDADE LIMITADA | 62.626.887/0001-85 | 24 | 8 | 9 | 0 | 44 | 17 | 19 | 31/12/2025 |
| ENDURANCE FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS RESPONSABILIDADE LIMITADA | 62.838.025/0001-16 | 10 | 3 | 6 | 0 | 17 | 8 | 5 | 22/09/2025 |
| PINE INSS III FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS RESPONSABILIDADE LIMITADA | 63.546.406/0001-94 | 9 | 3 | 1 | 4 | 27 | 14 | 12 | 22/04/2026 |
| SELLER 3 FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS SEGMENTO MEIOS DE PAGAMENTO DE RESP LIMITADA | 63.572.282/0001-11 | 10 | 4 | 3 | 3 | 31 | 22 | 9 | 23/01/2025 |

## Regras de interpretação

- Subordinação mínima, NPL Over por faixa, PDD/cobertura e alocação em direitos creditórios tendem a ser monitoráveis pelo IME quando a fórmula do documento usa os mesmos denominadores.
- Diluição, chargeback, concentração por cedente/sacado e critérios de elegibilidade granular normalmente não são monitoráveis pelo IME público.
- Reservas de liquidez e amortização são parcialmente monitoráveis: caixa existe no IME, mas cronogramas futuros costumam depender de suplemento, ata ou documento operacional.
- A presença de uma métrica no estudo não significa alerta automático; significa que o analista tem uma candidata a threshold manual para validação.
