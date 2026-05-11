# Investigação Fundos.NET — Resultados

## Escopo e amostra
- Fundo de teste principal: `33.254.370/0001-04`
- URL inicial usada na investigação: `https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM?cnpjFundo=33254370000104`
- Documento real baixado e inspecionado: `id=822193`
- Schema oficial consultado: `https://cvmweb.cvm.gov.br/SWB/Sistemas/SCW/PadroesXML/PadraoXMLMensalFIDC576.asp`

## Bloco A — Superfície pública

### HTML inicial observado
Requisição:

```http
GET /fnet/publico/abrirGerenciadorDocumentosCVM?cnpjFundo=33254370000104 HTTP/2
Host: fnet.bmfbovespa.com.br
```

Resposta relevante do HTML:

```html
<script>
    var csrf_token = "fceb21da-ac70-4cba-b5e4-97fe2b39a9ec";
</script>
...
<input type="hidden" id="idFundo" name="idFundo" multiple="multiple" value="" >
<input type="hidden" disabled="disabled" class="fundoItemInicial" data-id="18252"
  data-text="MERCADO CRÉDITO FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS  RESPONSABILIDADE LIMITADA" />
...
<img id="captchaAnexoBImg" src="/fnet/publico/captcha" ... />
...
<button type="button" id="btnAnexoB" ...>EXTRAIR INF. MENSAL</button>
...
<table id="tblDocumentosEnviados"><tbody></tbody></table>
```

Conclusões confirmadas:
- A página contém um identificador de fundo embutido: `data-id="18252"` em `.fundoItemInicial`.
- A grade nasce vazia no HTML; os dados são carregados via JavaScript.
- Há `csrf_token` embutido na página, mas ele não se mostrou necessário para os endpoints públicos relevantes.
- O botão `EXTRAIR INF. MENSAL` do modal usa captcha, mas isso se refere ao fluxo `validarAnexoB`/`cvmExportarAnexoB`, não ao fluxo de listagem + download de documentos.

### JavaScript da página
Arquivo lido:
- `https://fnet.bmfbovespa.com.br/fnet/resources/js/paginas/publico/gerenciador-documentos-cvm.js`

Trechos relevantes:

```javascript
ajax: {
    url: 'pesquisarGerenciadorDocumentosDados',
    type: 'GET',
    beforeSend: function ( xhr ) {
        xhr.setRequestHeader('CSRFToken', csrf_token);
    },
    data: function(params) {
        params = prepararRequisicaoDataTables( params );
        params.tipoFundo = $('#formListarDocumentosEnviadosCVM [name="tipoFundo"]').val();
        params.idFundo = $('#formListarDocumentosEnviadosCVM [name="idFundo"]').val() || '';
        params.idCategoriaDocumento = parseInt($('#formListarDocumentosEnviadosCVM [name="idCategoriaDocumento"]').val()) || 0;
        params.idTipoDocumento = parseInt($('#formListarDocumentosEnviadosCVM [name="idTipoDocumento"]').val()) || 0;
        params.idEspecieDocumento = parseInt($('#formListarDocumentosEnviadosCVM [name="idEspecieDocumento"]').val()) || 0;
        params.cnpj = $('#formListarDocumentosEnviadosCVM [name="cnpj"]').val();
        params.cnpjFundo = $('#formListarDocumentosEnviadosCVM [name="cnpj"]').val();
        params.dataReferencia = $('#formListarDocumentosEnviadosCVM [name="dataReferencia"]').val();
        params.dataInicial = $('#formListarDocumentosEnviadosCVM [name="dataInicial"]').val();
        params.dataFinal = $('#formListarDocumentosEnviadosCVM [name="dataFinal"]').val();
        ...
    }
}
```

Helper lido em `script.min.js`:

```javascript
function prepararRequisicaoDataTables(b){
    var n={d:b.draw,s:b.start,l:b.length,q:b.search.value};
    if(b.order&&b.order.length){
        var r=[],q;
        for(q in b.order){
            var c=b.order[q],d=b.columns[c.column].data;
            temp={}; temp[d]=c.dir; r.push(temp)
        }
        n.o=r
    }
    return n
}
```

Conclusão:
- O backend não recebe `draw/start/length`; ele recebe `d/s/l/q` e, opcionalmente, `o[n][campo]=asc|desc`.

## Bloco B — Mecanismo de listagem

## Endpoint de listagem
- URL exata: `https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados`
- Método HTTP confirmado: `GET`
- `POST` testado: respondeu `404`

### Parâmetros obrigatórios mínimos confirmados
Payload mínimo funcional:

```http
GET /fnet/publico/pesquisarGerenciadorDocumentosDados?d=1&s=0&l=1&cnpjFundo=33254370000104&tipoFundo=2&idCategoriaDocumento=6&idTipoDocumento=40
```

Observações:
- `d`, `s`, `l` são obrigatórios. Quando enviei `draw/start/length`, o backend respondeu:

```json
{"msg":"Deve ser informado o contador 'draw' no campo 'd' para as paginações!","dados":null,"erros":null}
```

- `cnpjFundo` sozinho funciona.
- `idFundo=18252` sozinho também funciona.
- `cnpjFundo + idFundo` funciona.
- `CSRFToken` não é necessário para o `GET` público.
- Cookies de sessão não são necessários para o `GET` público.
- `User-Agent` importa: `urllib` com UA padrão recebeu `403`, mas com UA de navegador recebeu `200`.

### Parâmetros opcionais confirmados
- `tipoFundo=2` para FIDC
- `idCategoriaDocumento`
- `idTipoDocumento`
- `idEspecieDocumento`
- `dataReferencia`
- `dataInicial`
- `dataFinal`
- `o[0][campo]=asc|desc`, `o[1][campo]=asc|desc` para ordenação
- `q` para busca textual

### Estrutura da resposta
Resposta observada:

```json
{
  "draw": 1,
  "recordsFiltered": 80,
  "recordsTotal": 80,
  "data": [
    {
      "id": 822193,
      "descricaoFundo": "...",
      "categoriaDocumento": "Informes Periódicos",
      "tipoDocumento": "Informe Mensal Estruturado ",
      "especieDocumento": "",
      "dataReferencia": "12/2024",
      "dataEntrega": "17/01/2025 09:24",
      "status": "AC",
      "descricaoStatus": "Ativo com visualização",
      "versao": 1,
      "modalidade": "AP",
      "descricaoModalidade": "Apresentação",
      "fundoOuClasse": "Classe",
      "...": "..."
    }
  ]
}
```

Campos relevantes identificados:
- Campo de id do documento: `id`
- Campo de data de referência/competência: `dataReferencia`
- Campo de data de entrega: `dataEntrega`
- Campo de tipo/categoria: `categoriaDocumento`, `tipoDocumento`, `especieDocumento`
- Campo de versão: `versao`
- Campo de status útil para retificações: `status`

### Descoberta dos IDs de categoria/tipo do IME
Endpoints auxiliares consultados:
- `GET /fnet/publico/listarTodasCategoriaPorTipoFundo?idTipoFundo=2`
- `GET /fnet/publico/listarTodosTiposPorCategoriaETipoFundo?idTipoFundo=2&idCategoria=6`

Resposta relevante:

```json
[{"id":6,"descricao":"Informes Periódicos",...}]
```

```json
[
  {"id":5,"descricao":"Informe Trimestral",...},
  {"id":30,"descricao":"Demonstrações Financeiras",...},
  {"id":40,"descricao":"Informe Mensal Estruturado ",...}
]
```

Conclusões confirmadas:
- `idCategoriaDocumento` do IME: `6`
- `idTipoDocumento` do IME: `40`
- `idEspecieDocumento`: vazio para IME do caso testado

### Filtro do IME confirmado
Payload funcional:

```http
GET /fnet/publico/pesquisarGerenciadorDocumentosDados?d=1&s=0&l=200&cnpjFundo=33254370000104&tipoFundo=2&idCategoriaDocumento=6&idTipoDocumento=40
```

Resposta:
- `recordsTotal=80`
- todos os itens retornados tinham `categoriaDocumento="Informes Periódicos"` e `tipoDocumento="Informe Mensal Estruturado "`

### Ordenação e paginação confirmadas
Payload funcional com ordenação:

```http
GET /fnet/publico/pesquisarGerenciadorDocumentosDados?d=1&s=0&l=10&cnpjFundo=33254370000104&tipoFundo=2&idCategoriaDocumento=6&idTipoDocumento=40&o[0][dataReferencia]=asc
```

Resultados:
- `o[0][dataReferencia]=asc` ordena corretamente por competência ascendente.
- `o[0][dataReferencia]=desc` ordena corretamente por competência descendente.
- `o[1][dataEntrega]=asc|desc` funciona como ordenação secundária.
- `s` e `l` paginam corretamente.
- Limite duro observado: `l <= 200`. Quando enviei `l=500`, o backend respondeu:

```json
{"msg":"O limite de itens para pesquisas é 200!","dados":null,"erros":null}
```

## Bloco C — Mecanismo de download

## Endpoint de download
- URL exata: `https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=822193`
- Requer sessão? `NÃO`
- Cookie necessário: nenhum
- `CSRFToken` necessário: não

### Resposta observada sem cookies
Headers:

```http
HTTP/2 200
content-type: text/xml
content-disposition: attachment; filename="33254370000104-IFP17012025V01-000822193.xml"
```

Corpo observado:

```text
"PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz48RE9DX0FSUS..."
```

Conclusão importante:
- O endpoint devolve o XML em `Base64`, entre aspas, apesar de anunciar `Content-Type: text/xml`.
- O cliente precisa:
  1. decodificar o corpo como texto UTF-8,
  2. remover aspas externas, se presentes,
  3. aplicar `base64.b64decode`.

### Resposta observada com `urllib`
- `User-Agent` padrão do Python: `HTTP 403`
- `User-Agent` de navegador: `HTTP 200`

### Visualização HTML
Endpoint testado:
- `https://fnet.bmfbovespa.com.br/fnet/publico/visualizarDocumento?id=822193&cvm=true`

Resultado:
- responde `text/html`
- não é necessário para o caso de uso; o download direto é suficiente

## Bloco D — XML real e schema

## XML real baixado
- Documento usado: `822193`
- Competência do XML: `DT_COMPT=12/2024`
- Encoding declarado no XML real: `UTF-8`
- Root tag real: `DOC_ARQ`
- Namespace real: não há `xmlns="urn:fidc"` no XML real; só `xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"`

Início do XML real:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<DOC_ARQ xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <CAB_INFORM>
    <VERSAO>6.1</VERSAO>
    <DT_COMPT>12/2024</DT_COMPT>
    <CLASS_UNICA>NAO</CLASS_UNICA>
    <NR_CNPJ_ADM>36266751000100</NR_CNPJ_ADM>
    <NR_CNPJ_FUNDO>33254370000104</NR_CNPJ_FUNDO>
    <NM_CLASSE>Subordinada</NM_CLASSE>
    <NR_CNPJ_CLASSE>33254370000104</NR_CNPJ_CLASSE>
```

### Blocos presentes no XML real
- `CAB_INFORM`
- `LISTA_INFORM/APLIC_ATIVO`
- `LISTA_INFORM/CART_SEGMT`
- `LISTA_INFORM/PASSIV`
- `LISTA_INFORM/PATRLIQ`
- `LISTA_INFORM/COMPMT_DICRED_AQUIS`
- `LISTA_INFORM/COMPMT_DICRED_SEM_AQUIS`
- `LISTA_INFORM/NEGOC_DICRED_MES`
- `LISTA_INFORM/TAXA_NEGOC_DICRED_MES`
- `LISTA_INFORM/OUTRAS_INFORM`

### Estruturas repetitivas observadas no XML real
- `LISTA_CEDENT_CRED_EXISTE/CEDENT_CRED_EXISTE[1..n]`
- blocos de cotistas/classe/série dentro de `OUTRAS_INFORM`

Exemplo:

```xml
<LISTA_CEDENT_CRED_EXISTE>
  <CEDENT_CRED_EXISTE>
    <NR_PF_PJ_CEDENT_CRED_EXISTE>11581339000145</NR_PF_PJ_CEDENT_CRED_EXISTE>
    <PR_CEDENT_CRED_EXISTE>82,85</PR_CEDENT_CRED_EXISTE>
  </CEDENT_CRED_EXISTE>
  ...
</LISTA_CEDENT_CRED_EXISTE>
```

Decisão derivada:
- dados repetitivos devem ir para worksheet separada, em formato tidy, com `list_path`, `list_index`, `tag_path` e competência.

### Comparação com o schema oficial ICVM 576
Schema oficial publicado:
- declara `encoding="windows-1252"`
- declara `DOC_ARQ xmlns="urn:fidc"`

XML real:
- declara `encoding="UTF-8"`
- não declara `xmlns="urn:fidc"`
- traz tags adicionais e omite algumas tags antigas

Tags extras observadas no XML real que não aparecem na página oficial ICVM 576:
- `VERSAO`
- `CLASS_UNICA`
- `NM_CLASSE`
- `NR_CNPJ_CLASSE`
- `VL_CLS_COTA_FIF`
- `QT_COTISTAS`
- `VL_AA`
- `VL_A`
- `VL_B`
- `VL_C`
- `VL_D`
- `VL_E`
- `VL_F`
- `VL_G`
- `VL_H`
- `VLR_TOTAL_DIR_CRD_DEVD`
- `VLR_TOTAL_DIR_CRD_OP`
- `REG_TRIB_CED`
- `RES_INF_PRST_SCR`
- e outras listadas na comparação automática feita durante a investigação

Tags do schema oficial não vistas na amostra real:
- `PR_ENTRE_RESGATE`
- `TP_DIAS_RESGATE`
- `PR_ENTRE_CONVER`
- `TP_DIAS_CONVER`
- `VL_OUTROS_CRED`
- `VL_DICRED_OUTROS_CRED`
- `LISTA_CEDENT`
- `CEDENT`
- `NR_PF_PJ_CEDENT`
- `PR_CEDENT`
- `VL_COTA_FDO_ICVM409`
- `VL_COTA_FIDC_NAO_PADRAO`
- `LISTA_DEV_SACADOS`
- `DEV_SACADOS`
- `NR_PF_PJ_SACADO_DEVED_1`
- `VL_SACADO_DEVED_1`
- `PR_SACADO_DEVED_1`
- `VL_SOM_LISTA_DEV_SACADOS`
- `PR_SOM_LISTA_DEV_SACADOS`
- `VL_CLASSE`

Conclusão:
- a página oficial ICVM 576 é útil como referência descritiva, mas está defasada em relação ao XML real atual servido pelo Fundos.NET.

### Separador decimal confirmado
Achados no XML real:
- monetários e percentuais tradicionais: vírgula decimal, ex. `30761196,40`, `82,85`
- alguns campos atuais usam ponto decimal, ex.:
  - `VL_COTAS=1205.78565646`
  - `PR_APURADA=1.16`
  - `VL_TOTAL=0.00`
  - `VL_PAGO=0.00`
  - `DESEMP_ESP=0.93`

Conclusão:
- o parser precisa aceitar vírgula e ponto como decimal, além de sinal negativo.
- a regra histórica da página oficial (“vírgula deve ser usada”) não bate integralmente com o XML real atual.

### Formato de data confirmado
- `DT_COMPT`: `MM/YYYY`
- `dataReferencia` na listagem do IME: `MM/YYYY`
- `dataEntrega`: `DD/MM/YYYY HH:mm`

## Bloco E — Cobertura temporal e retificações

### Cobertura observada para o fundo de teste
- Total bruto de IMEs listados: `80`
- Janela das 24 competências mais recentes observada no dataset: `03/2024` a `02/2026`
- Nessa janela de 24 competências:
  - documentos brutos: `32`
  - competências únicas: `24`

### Duplicatas / retificações observadas
Competências com múltiplos documentos:
- `09/2021`: `v1 IC`, `v2 AC`
- `05/2022`: `v1 IC`, `v2 IC`, `v3 AC`
- `07/2022`: `v1 IC`, `v2 AC`
- `01/2023`: `v1 IC`, `v2 AC`
- `08/2023`: `v1 IC`, `v2 IC`, `v3 AC`
- `09/2023`: `v1 IC`, `v2 AC`
- `06/2024`: `v1 IC`, `v2 AC`
- `06/2025`: `v1 IC`, `v2 IC`, `v3 AC`
- `07/2025`: `v1 IC`, `v2 IC`, `v3 AC`
- `09/2025`: `v1 IC`, `v2 AC`
- `01/2026`: `v1 IC`, `v2 AC`
- `02/2026`: `v1 IC`, `v2 AC`

Padrão observado:
- a maior `versao` coincide com o maior `dataEntrega`
- a maior `versao` coincide com `status=AC`
- versões anteriores ficam `IC`

## Critério de seleção de versão em caso de retificação
- Agrupar por competência (`dataReferencia`)
- Preferir `status` ativo (`A*`, na prática `AC`)
- Dentro do grupo, preferir maior `versao`
- Em empate, preferir maior `dataEntrega`
- Em empate residual, preferir maior `id`

Esse critério foi consistente em todos os casos duplicados observados.

## Bloco F — Robustez e fragilidade

## Cloudflare / bot detection
Evidências:
- `curl -I` em algumas URLs respondeu `HTTP 520` da Cloudflare, enquanto `GET` normal funcionou.
- `urllib` com `User-Agent` padrão recebeu `HTTP 403` tanto na listagem quanto no download.
- `urllib` com `User-Agent` de navegador recebeu `HTTP 200`.
- `curl` padrão funcionou nos endpoints públicos relevantes.

Conclusão:
- há algum fingerprinting/bot detection leve na borda; o ponto mínimo confirmado é a necessidade prática de um `User-Agent` realista para clientes Python.

## CSRF
Evidências:
- o HTML injeta `csrf_token`
- o JavaScript da página manda `CSRFToken` em vários requests
- porém, o `GET` público de listagem funcionou sem `CSRFToken`
- o `downloadDocumento` funcionou sem `CSRFToken`

Conclusão:
- `CSRFToken` não é necessário para o fluxo público de listagem + download usado neste projeto.

## Rate limiting
Evidências:
- não foram observados headers `X-RateLimit-*`
- não foi observado `Retry-After`
- não houve `429` durante dezenas de requisições ao longo da investigação

Conclusão:
- não há evidência de rate limit explícito no fluxo público testado, mas existe proteção de borda suficiente para justificar retry com backoff e `User-Agent` de navegador.

## Estabilidade dos IDs
- `idCategoriaDocumento=6` e `idTipoDocumento=40` foram obtidos do endpoint auxiliar oficial do próprio site, não inferidos só por texto.
- Isso é mais estável do que hardcode “cego”, mas ainda depende da taxonomia atual do Fundos.NET.

Endpoints auxiliares úteis:
- `listarTodasCategoriaPorTipoFundo?idTipoFundo=2`
- `listarTodosTiposPorCategoriaETipoFundo?idTipoFundo=2&idCategoria=6`
- `listarMapaTemplate`

## Alternativa mais estável / oficial
Alternativa encontrada:
- Dataset oficial da CVM: `https://dados.cvm.gov.br/dataset/fidc-doc-inf_mensal`

Limitação objetiva observada:
- o portal informa que somente os arquivos dos meses `M-1` a `M-12` são atualizados semanalmente
- os recursos são ZIPs mensais tabulares, não o XML individual do Fundos.NET

Conclusão:
- é uma alternativa oficial relevante, mas não substitui o caso de uso deste projeto para histórico arbitrário por documento nem para extração do XML individual real do IME.

## Decisões arquiteturais derivadas da investigação
- Não usar o fluxo `btnAnexoB`/captcha.
- Integrar com os endpoints públicos `GET` de listagem e download.
- Usar `User-Agent` de navegador explicitamente no cliente Python.
- Paginar com `l<=200`.
- Filtrar IME por `tipoFundo=2`, `idCategoriaDocumento=6`, `idTipoDocumento=40`.
- Não filtrar por intervalo de competências no backend; fazer paginação completa do IME e filtrar localmente por `dataReferencia`/`DT_COMPT`.
- Deduplicar retificações localmente por competência usando `status`, `versao`, `dataEntrega`, `id`.
- Decodificar Base64 no download antes do parse XML.
- Aceitar XML real em `UTF-8`, sem namespace `urn:fidc`, e números com vírgula ou ponto decimal.
- Separar campos escalares e estruturas repetitivas em folhas distintas no Excel.
