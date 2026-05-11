# Modelo Financeiro FIDC (Streamlit)

Aplicação Streamlit para rodar o modelo financeiro do FIDC com dados base em
`model_data.json` (sem depender de upload do `.xlsm`).

## Requisitos

- Python 3.10+
- Dependências listadas em `requirements.txt`

```bash
pip install -r requirements.txt
```

## Executar

```bash
streamlit run app.py
```

> Execute o comando na raiz do repositório (mesma pasta de `app.py`).

## O que o app faz

- Carrega premissas, feriados, curvas e timeline do `model_data.json`.
- Permite ajustar premissas via inputs numéricos e sliders.
- Exibe KPIs, gráficos e tabela da timeline.
- Oferece exportação de resultados em CSV/Excel.

## Dados

O arquivo `model_data.json` contém os dados base extraídos do modelo original
(premissas, feriados, curva CDI/DU e amostra de validação).

## Pipeline Fundos.NET (CVM)

Para automatizar download de **Informes Mensais Estruturados (FIDC)** via endpoint público do Fundos.NET:

```bash
python fundonet_fidc_pipeline.py \
  --cnpj-fundo 12345678000199 \
  --periodo-inicio Jan-25 \
  --periodo-fim Jan-26 \
  --output-dir saida_fundonet
```

Saídas geradas:
- `documentos_filtrados.csv`: metadados dos documentos encontrados.
- `informes_tidy.csv`: campos escalares dos XMLs no formato tidy.
- `estruturas_lista.csv`: estruturas repetitivas (cedentes, classes/séries etc.) em formato tidy.
- `informes_wide.xlsx`: workbook com abas `informes_campos`, `estruturas_lista`, `documentos` e `auditoria`.
- `audit_log.json`: trilha de auditoria da execução.

Observações:
- O script pagina automaticamente o endpoint `pesquisarGerenciadorDocumentosDados`.
- O download é feito por `downloadDocumento?id=...`.
- O filtro funcional usa o tipo FIDC + categoria/tipo oficiais do IME no Fundos.NET.
- O recorte temporal é por competência (`MM/AAAA`), não por data de entrega.
