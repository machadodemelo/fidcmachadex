# Estudo Pravaler / Crédito Universitário — critérios monitoráveis, emissões e calendário

Data da revisão: 2026-05-10

## Escopo

Fundos analisados:

| Fundo | CNPJ | Regulamento-base usado |
| --- | --- | --- |
| Crédito Universitário FIDC | 08.417.544/0001-65 | `784311_regulamento_regulamento_784311_2024-11-18.pdf` |
| Pravaler Crédito Universitário II FIDC | 26.749.095/0001-34 | `1061833_regulamento_regulamento_1061833_2025-11-19.pdf` |
| Crédito Universitário III FIDC | 34.408.539/0001-04 | `939590_regulamento_regulamento_939590_2025-04-15.pdf` |
| Crédito Universitário IV FIDC | 55.983.705/0001-68 | `1149324_regulamento_regulamento_1149324_2026-03-26.pdf` |

A leitura foi feita localmente sobre PDFs em `data/raw/<cnpj>/` e sobre a base estruturada `data/regulatory_knowledge/<cnpj>.json`. Não houve chamada externa de LLM.

Arquivos adicionados ao app:

- `data/regulatory_profiles/pravaler_criteria_monitoraveis_ime.csv`
- `data/regulatory_profiles/pravaler_cotas_emissoes_pagamentos.csv`

Esses arquivos passam a ter precedência sobre a triagem geral `all_fidcs_*` para os quatro CNPJs, evitando misturar linhas heurísticas com linhas revisadas.

## Conclusões principais

1. **Os índices de atraso da família Pravaler não são exatamente o bucket CVM simples.** Os regulamentos usam conceito por devedor cedido com ao menos um direito creditório vencido, normalmente calculado no sexto mês após a cessão, e sem deduzir provisões. O IME é uma proxy útil, mas deve aparecer como “monitorável com ressalva”.
2. **Crédito Universitário I e IV têm limites de atraso iguais:** Over 30 > 14%, Over 60 > 12%, Over 90 > 10,5% e Over 180 > 8%.
3. **Crédito Universitário II tem limites mais apertados:** Over 30 > 12%, Over 60 > 10%, Over 90 > 8,5% e Over 180 > 6%.
4. **Crédito Universitário III, no regulamento vigente revisado, trouxe threshold explícito apenas para Over 90:** superior a 19%. Não registrei limites Over 30/60/180 para esse fundo sem evidência documental no regulamento vigente.
5. **Há métricas de cobertura/índice de cobertura que não são PDD/Over.** Elas dependem de valor presente dos direitos creditórios, disponibilidades, fatores de ponderação e classe/série. Devem ser qualitativas ou input manual, não alerta automático derivado de PDD.
6. **Reservas de liquidez/amortização dependem de fluxo futuro.** O IME traz disponibilidades, mas não reconstrói sozinho Reserva de Amortização, Reserva de Fluxo de Caixa e despesas futuras.
7. **Derivativos são permitidos para hedge de juros/inflação até 1x PL em I, II e IV; III também permite hedge de juros/inflação.** O IME só mostra posição agregada em derivativos, não finalidade.

## Critérios monitoráveis por IME

| Fundo | Critério | Regra documental | Como monitorar no IME | Grau |
| --- | --- | --- | --- | --- |
| Crédito Universitário I | Relação Mínima | PL / Cotas Sênior >= 105% | Proxy por Cotas SR / PL <= 95,24% | Monitorável com ressalva |
| Crédito Universitário I | Alocação mínima | Dir Cred / PL >= 50% | Dir Cred / PL | Monitorável com ressalva |
| Crédito Universitário I | Atraso Over 30/60/90/180 | 14% / 12% / 10,5% / 8% | NPL Over acumulado por faixa / crédito | Monitorável com ressalva |
| Crédito Universitário II | Relação mínima total | Cotas Sub / PL >= 22%; sobe para 27% se Over 60 >= 6% | Cotas Sub / PL + Over 60 | Monitorável com ressalva |
| Crédito Universitário II | Relação mínima junior | Junior / PL >= 10%; sobe para 15% se Over 60 >= 6% | Exige segregação junior/mezanino | Parcial |
| Crédito Universitário II | Alocação mínima | Dir Cred / PL >= 50% | Dir Cred / PL | Monitorável com ressalva |
| Crédito Universitário II | Atraso Over 30/60/90/180 | 12% / 10% / 8,5% / 6% | NPL Over acumulado por faixa / crédito | Monitorável com ressalva |
| Crédito Universitário III | Razão de Subordinação Sênior | Cotas Sub / PL >= 12% | Cotas Sub / PL | Monitorável com ressalva |
| Crédito Universitário III | Alocação mínima | Dir Cred / PL >= 50% | Dir Cred / PL | Monitorável com ressalva |
| Crédito Universitário III | Inadimplência Over 90 | Over 90 > 19% | NPL Over 90 acumulado / crédito | Monitorável com ressalva |
| Crédito Universitário IV | Índice de Subordinação Mezanino | Junior / PL >= 7% | Exige segregação junior/mezanino | Parcial |
| Crédito Universitário IV | Índice de Subordinação Sênior | Cotas Sub / PL >= 15% | Cotas Sub / PL | Monitorável com ressalva |
| Crédito Universitário IV | Alocação mínima | Dir Cred / PL >= 67% | Dir Cred / PL | Monitorável com ressalva |
| Crédito Universitário IV | Atraso Over 30/60/90/180 | 14% / 12% / 10,5% / 8% | NPL Over acumulado por faixa / crédito | Monitorável com ressalva |

## Emissões e calendário

O arquivo `pravaler_cotas_emissoes_pagamentos.csv` consolida eventos de emissão identificados nos documentos locais. Para as séries antigas, muitos documentos trazem aprovação/volume e regra genérica de carência/amortização, mas não uma tabela fechada de datas. Esses casos estão marcados como `curado parcial; evento identificado, cronograma incompleto`.

Resumo por fundo:

| Fundo | Eventos de cota registrados | Observação |
| --- | ---: | --- |
| Crédito Universitário I | 9 | Séries 25, 26, 27, 29, 31, 33, 34, 35 e Mezanino II-D. Cronogramas antigos incompletos nos PDFs baixados. |
| Crédito Universitário II | 6 | Séries 7, 8, 10, 11, 12 e 13. Cronogramas fechados de amortização não foram identificados de forma completa. |
| Crédito Universitário III | 3 | Eventos de Cotas Seniores III, Subordinadas Júnior e 1ª série; poucos anúncios formais de oferta na base local. |
| Crédito Universitário IV | 4 | Séries 1, 2 e 3, mais Subordinada Júnior. A 3ª série tem documentos de abril de 2026. |

## Pontos que não viraram alerta automático

- Índice de Cobertura Sênior/Mezanino: depende de valor presente, fatores de ponderação e disponibilidades comprometidas/livres. Não é equivalente a PDD / Over.
- Reserva de Liquidez: depende de fluxo de caixa futuro, próxima amortização e despesas/encargos.
- Critérios de elegibilidade granular: exigem carteira individual dos contratos cedidos.
- Eventos societários, ratings e prestadores: exigem documentos externos/ratings ou acompanhamento qualitativo.

## Próxima curadoria recomendada

1. Fechar os cronogramas de amortização das séries antigas consultando suplementos/apêndices que não apareceram completos na extração textual.
2. Cadastrar fatores de ponderação por classe/série para transformar Índice de Cobertura em cálculo monitorável.
3. Revisar manualmente a classificação de junior vs mezanino nos XMLs de cada fundo antes de ativar alertas automáticos de subordinação por camada.
4. Repetir o mesmo padrão de curadoria parcial para as próximas famílias: Mercado Crédito, Cloudwalk e FGTS/INSS.
