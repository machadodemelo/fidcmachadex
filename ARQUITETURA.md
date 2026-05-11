# Arquitetura

## 1. Estratégia de integração escolhida e por quê

### Estratégia escolhida
Usar o fluxo público do Fundos.NET em duas etapas:
1. `GET /fnet/publico/pesquisarGerenciadorDocumentosDados`
2. `GET /fnet/publico/downloadDocumento?id=...`

### Por que essa estratégia foi escolhida
Porque a investigação confirmou que:
- a listagem pública funciona por `GET` com `cnpjFundo`, `tipoFundo=2`, `idCategoriaDocumento=6`, `idTipoDocumento=40`
- o download do documento também é público
- o fluxo com captcha (`validarAnexoB` / `cvmExportarAnexoB`) não é necessário para obter os XMLs individuais
- o único cuidado prático obrigatório para Python é usar `User-Agent` de navegador

### Estratégia explicitamente rejeitada
- Não usar `btnAnexoB`/captcha.
- Não depender do dataset aberto da CVM como fonte principal.
  - motivo: ele é útil como alternativa oficial, mas não cobre o caso histórico arbitrário por documento XML individual.

## 2. Gestão de sessão

### Decisão
Não tratar sessão como requisito funcional do fluxo principal.

### Racional
A investigação mostrou que:
- listagem pública funciona sem cookie e sem `CSRFToken`
- download público funciona sem cookie e sem `CSRFToken`
- o que efetivamente bloqueia o cliente Python é `User-Agent` padrão

### Implementação derivada
- o cliente HTTP sempre usará `User-Agent` de navegador
- o cliente pode abrir a página pública do gerenciador para obter contexto auxiliar (`data-id`, nome do fundo, `csrf_token`), mas isso é contexto opcional, não pré-condição da listagem/download

## 3. Camadas de software

## 3.1 Cliente HTTP
Arquivo:
- `services/fundonet_client.py`

Responsabilidades:
- normalizar CNPJ
- abrir a página pública do gerenciador e extrair contexto opcional do fundo
- paginar a listagem pública do IME
- ordenar e filtrar documentos no backend apenas pelo que o endpoint suporta
- baixar o payload do documento
- decodificar Base64 do corpo de `downloadDocumento`
- encapsular retries, timeout e erros de provedor

## 3.2 Parser XML
Arquivo:
- `services/fundonet_parser.py`

Responsabilidades:
- fazer parse do XML real do IME
- separar dados escalares e estruturas repetitivas
- produzir `tag_path`
- identificar `bloco`, `sub_bloco`, `tag`
- normalizar valores numéricos aceitando vírgula e ponto decimal
- preservar também o valor bruto textual
- anexar descrição oficial quando houver correspondência não ambígua com o schema publicado

## 3.3 Serviço orquestrador
Arquivo:
- `services/fundonet_service.py`

Responsabilidades:
- validar entrada
- obter lista de documentos IME
- filtrar por intervalo de competência localmente
- deduplicar retificações
- iterar downloads/parses com tolerância a falhas individuais
- consolidar dataframes de saída
- expor metadados, auditoria e payload pronto para exportação

## 3.4 Exportador Excel
Arquivo:
- `services/fundonet_export.py`

Responsabilidades:
- montar sheet wide principal
- montar sheet tidy de estruturas repetitivas
- montar sheets auxiliares (`documentos`, `auditoria`, opcionalmente `falhas`)
- garantir ordenação cronológica crescente das competências
- garantir ordenação hierárquica das linhas

## 3.5 UI Streamlit
Arquivos:
- `app.py`
- `tabs/tab_fidc_ime.py`

Responsabilidades:
- coletar CNPJ e intervalo de competências
- mostrar progresso e mensagens limpas
- chamar o serviço
- exibir preview, documentos processados, falhas e botão de download

## 4. Modelo tidy dos dados

### 4.1 Documento selecionado
Cada documento IME selecionado terá metadados como:
- `documento_id`
- `competencia`
- `data_referencia_listagem`
- `data_entrega`
- `versao`
- `status`
- `categoria`
- `tipo`
- `especie`
- `fundo_ou_classe`

### 4.2 Campos escalares
Para cada leaf não repetitivo do XML:
- `documento_id`
- `competencia`
- `bloco`
- `sub_bloco`
- `tag`
- `tag_path`
- `schema_path_match`
- `descricao`
- `valor_raw`
- `valor_num`
- `ordem_hierarquica`

Observações:
- `tag_path` será a chave semântica principal.
- `descricao` virá do schema oficial quando a correspondência for inequívoca.
- para tags reais não documentadas na página ICVM 576, a descrição ficará explicitamente vazia/não documentada, sem invenção.

### 4.3 Estruturas repetitivas
Para listas como cedentes e blocos análogos:
- `documento_id`
- `competencia`
- `list_path`
- `list_item_tag`
- `list_index`
- `bloco`
- `sub_bloco`
- `tag`
- `tag_path`
- `descricao`
- `valor_raw`
- `valor_num`
- `ordem_hierarquica`

## 5. Modelo wide para o Excel

## 5.1 Worksheet principal
Nome sugerido:
- `informes_campos`

Linhas:
- uma linha por `tag_path` escalar

Colunas fixas:
- `bloco`
- `sub_bloco`
- `tag`
- `tag_path`
- `descricao`

Colunas dinâmicas:
- uma coluna por competência (`MM/YYYY`)

Ordenação:
- competências em ordem cronológica crescente
- linhas em ordem hierárquica do XML/schema

## 5.2 Worksheet de listas
Nome sugerido:
- `estruturas_lista`

Formato:
- tidy, não wide

Colunas:
- `competencia`
- `documento_id`
- `list_path`
- `list_item_tag`
- `list_index`
- `tag`
- `tag_path`
- `descricao`
- `valor_raw`
- `valor_num`

### Motivo
As listas variam em cardinalidade entre competências; forçar pivot wide nelas gera planilha instável e difícil de consumir.

## 5.3 Worksheets auxiliares
Sugestão:
- `documentos`
- `auditoria`

Objetivo:
- tornar explícito quais documentos foram escolhidos, quais falharam e por quê

## 6. Política de retry, timeout e tratamento de erro

## 6.1 Cliente HTTP
- timeout por requisição: curto/moderado (ex.: 30s)
- retries: apenas para erros transitórios
- backoff exponencial pequeno
- tratar explicitamente:
  - `403` como provável bloqueio por fingerprint/UA
  - `429`/`5xx` como indisponibilidade transitória
  - corpo inesperado como erro de provedor

## 6.2 Serviço
- erro de um documento:
  - registrar em auditoria
  - continuar os demais
- erro de todos os documentos:
  - falhar o processamento com mensagem limpa e trilha auditável
- ausência total de IME no período:
  - erro funcional explícito, sem traceback bruto

## 6.3 UI
- nunca exibir traceback cru ao usuário final
- mostrar:
  - resumo do erro
  - quantidade de documentos encontrados/processados/falhados
  - auditoria baixável

## 7. Tratamento de retificações

Critério adotado, derivado da investigação:
1. agrupar por competência
2. preferir documento com status ativo (`A*`, na prática `AC`)
3. preferir maior `versao`
4. preferir maior `dataEntrega`
5. preferir maior `id`

### Justificativa
Esse padrão foi consistente em todas as competências duplicadas observadas no fundo de teste.

## 8. Dependências novas necessárias

### Decisão
Nenhuma dependência nova é necessária para a feature.

### Racional
- `urllib`/`http.cookiejar`/`base64`/`xml.etree.ElementTree` cobrem o cliente e o parse do payload do download
- `pandas`, `openpyxl` e `streamlit` já constam do projeto

### Decisão complementar
- remover a dependência funcional de `requests` do cliente Fundos.NET
  - motivo: simplifica o runtime e elimina uma dependência que não estava instalada no ambiente atual

## 9. Consequências diretas para a implementação
- o filtro da UI deve ser de competência, não de data de entrega
- o serviço deve carregar todos os IMEs paginados do fundo e só depois aplicar o recorte temporal por competência
- o parser não pode assumir atributos de “conta”; ele precisa usar hierarquia XML real
- o download precisa decodificar Base64 antes do parse
- a exportação precisa ter pelo menos duas sheets: campos escalares wide e listas tidy
