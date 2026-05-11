# Diagnóstico do Repositório

## Estrutura de arquivos

Observação:
- `tree` foi tentado conforme solicitado, mas o binário não está instalado no ambiente (`zsh:1: command not found: tree`).
- O mapeamento foi concluído com `find . -maxdepth 3 -print | sort`.

Estrutura observada:

```text
.
./Modelo_Publico.xlsm
./README.md
./app.py
./data_loader.py
./docs
./docs/arquitetura_informe_mensal_fidc.md
./fundonet_fidc_pipeline.py
./model.py
./model_data.json
./model_pack_formulas.json
./requirements.txt
./services
./services/__init__.py
./services/fundonet_client.py
./services/fundonet_errors.py
./services/fundonet_export.py
./services/fundonet_models.py
./services/fundonet_parser.py
./services/fundonet_service.py
./tests
./tests/test_fundonet_service.py
./validation.py
```

## Como app.py registra abas
- `app.py` usa `st.tabs(["Modelo FIDC", "Informes Mensais Estruturados"])`.
- A aba de modelo está implementada inline em `render_modelo_tab()`.
- A aba de Fundos.NET também está inline em `render_informes_tab()`.
- Hoje não existe pasta `tabs/`.

Conclusão:
- a nova UI deve ser extraída para `tabs/tab_fidc_ime.py`, mantendo `app.py` como registrador simples de abas para reduzir acoplamento.

## Arquivos em services/ e o que fazem

### `services/fundonet_client.py`
Função atual:
- usa `requests.Session`
- tenta bootstrap de sessão/CSRF
- resolve fundo por `listarFundos`
- lista documentos por `pesquisarGerenciadorDocumentosDados`
- baixa documento por `downloadDocumento`

Problemas em relação à investigação:
- ainda depende de `listarFundos`, mas a investigação mostrou que `cnpjFundo` sozinho já resolve a listagem pública.
- filtra por `dataInicial`/`dataFinal`, que são datas de entrega, não intervalo de competência.
- manda `o` como JSON string (`json.dumps([{"dataEntrega": "desc"}])`), mas o backend real do DataTables espera a serialização `o[0][campo]=...`.
- usa `requests`, mas no ambiente atual a dependência não está instalada; além disso, a investigação mostrou que o requisito essencial é `User-Agent` de navegador, não `requests` em si.
- retorna `response.content` bruto no download, mas o corpo real vem em Base64 entre aspas e precisa ser decodificado antes do parse XML.

### `services/fundonet_parser.py`
Função atual:
- tenta transformar XML em linhas de “contas” com base em atributos como `codigoConta`, `descricaoConta`, `codConta`

Problemas em relação à investigação:
- o XML real do IME não expõe esses atributos de conta.
- o modelo atual pressupõe um XML “contábil” com hierarquia de contas, o que não corresponde ao XML real baixado do Fundos.NET.
- `_parse_br_number` remove todos os pontos antes de trocar vírgula por ponto, o que corromperia campos reais como `VL_COTAS=1205.78565646` e `PR_APURADA=1.16`.
- não separa estruturas repetitivas (cedentes, classes/séries etc.).

### `services/fundonet_service.py`
Função atual:
- valida entrada
- resolve fundo
- lista documentos
- filtra por texto “Informe Mensal Estruturado”
- baixa e parseia todos os documentos
- monta dataset wide e Excel

Problemas em relação à investigação:
- usa intervalo por data de entrega recebido do `app.py`, não intervalo de competência.
- em caso de falha de um documento, aborta o batch com `DocumentDownloadError`; isso viola a regra do prompt de continuar os demais.
- ordena documentos por `periodo_ordenacao` baseado em parse limitado (`%d/%m/%Y`, `%Y-%m-%d`, `%Y-%m-%dT%H:%M:%S`), mas `dataReferencia` do IME é `MM/YYYY`.
- não deduplica retificações por competência.
- não valida coerência entre `dataReferencia` da grade e `DT_COMPT` do XML.

### `services/fundonet_export.py`
Função atual:
- faz pivot simples por `conta_codigo`, `conta_descricao`, `conta_caminho`
- gera Excel com uma única worksheet

Problemas em relação à investigação:
- o XML real não é naturalmente um plano de contas.
- o layout exportado não atende o requisito de colunas auxiliares por `bloco`, `sub-bloco`, `tag`, `tag_path`, `descrição`.
- não há worksheet separada para listas repetitivas.

### `services/fundonet_models.py`
Função atual:
- define `FundoResolution` e `DocumentoFundo`

Pontos úteis:
- dataclasses existentes podem ser reaproveitadas parcialmente, mas `DocumentoFundo` precisa ganhar semântica de competência, status e versão.

### `services/fundonet_errors.py`
Função atual:
- centraliza exceções específicas

Pontos úteis:
- é reaproveitável e deve ser complementado, não substituído.

## O que pode ser reaproveitado (e por quê)
- `services/fundonet_errors.py`
  - a hierarquia de erros já está clara e aderente ao domínio.
- partes de `services/fundonet_models.py`
  - o conceito de `DocumentoFundo` é válido; a estrutura precisa ser ampliada.
- `fundonet_fidc_pipeline.py`
  - o wrapper CLI é útil e deve continuar chamando o serviço principal, sem duplicar lógica.
- o uso de `st.cache_data` em `app.py`
  - a ideia é boa, mas o contrato da função cacheada deve mudar para competência e não data de entrega.

## O que NÃO deve ser reaproveitado (e por quê)
- a lógica atual de parse em `services/fundonet_parser.py`
  - está baseada num shape de XML que não corresponde ao IME real.
- a serialização atual de `o` em `services/fundonet_client.py`
  - não corresponde ao contrato real do DataTables no backend.
- a estratégia atual de filtro por período em `services/fundonet_service.py`
  - filtra por data de entrega, não por competência.
- a política atual de abortar o batch ao primeiro erro
  - conflita com o requisito funcional explícito.
- o layout wide atual de `services/fundonet_export.py`
  - não atende o contrato de saída pedido pelo usuário.

## Dependências disponíveis
`requirements.txt` atual:

```text
openpyxl
pandas
streamlit
altair<5
standard-imghdr
requests
```

Observações:
- `requests` está listado, mas não está instalado no ambiente atual de execução do agente.
- como a investigação mostrou que `urllib` + `User-Agent` de navegador resolve o caso, a dependência `requests` não é necessária para a feature.

## Onde registrar a nova aba
- Em `app.py`
- Recomendação: `app.py` só registra `st.tabs(...)` e delega renderização da aba IME para `tabs/tab_fidc_ime.py`

## Onde colocar o cliente HTTP
- `services/fundonet_client.py`
- Recomendação: reescrever/estender para usar o contrato real confirmado do Fundos.NET

## Onde colocar o parser
- `services/fundonet_parser.py`
- Recomendação: substituir a lógica “contábil” atual por um parser baseado em `tag_path`, listas repetitivas e normalização de valores

## Onde colocar o serviço orquestrador
- `services/fundonet_service.py`
- Recomendação: centralizar ali a paginação, deduplicação por competência, tolerância a falhas individuais e montagem dos dataframes de saída

## Onde colocar o exportador Excel
- `services/fundonet_export.py`
- Recomendação: manter esse arquivo, mas refazer o contrato para suportar múltiplas worksheets

## Onde colocar a UI da nova aba
- Criar `tabs/tab_fidc_ime.py`
- `app.py` passa a importar e chamar `render_tab_fidc_ime()`

## Riscos de regressão identificados
- `app.py` já tem uma aba Fundos.NET; uma alteração descuidada pode quebrar a aba existente ou conflitar com o cache atual.
- `fundonet_fidc_pipeline.py` já consome `InformeMensalService`; mudar o contrato do serviço sem ajustar o wrapper quebra o fluxo CLI.
- o parser atual e o exportador atual partem de um modelo de “contas”; qualquer reutilização parcial desse shape sem revisão causará dataset incorreto silenciosamente.
- se `requests` continuar importado no cliente, o app pode falhar ao iniciar em ambientes onde as dependências ainda não foram instaladas.
- se o novo serviço continuar usando `dataInicial`/`dataFinal` como critério funcional, a UI parecerá correta mas entregará meses errados.
