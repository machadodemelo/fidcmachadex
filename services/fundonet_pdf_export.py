from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services.fundonet_dashboard import FundonetDashboardData
from services.identifier_utils import format_cnpj


PAGE_SIZE = landscape(A4)
PAGE_WIDTH = PAGE_SIZE[0]
LEFT_MARGIN = 14 * mm
RIGHT_MARGIN = 14 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN


def build_dashboard_pdf_bytes(
    dashboard: FundonetDashboardData,
    *,
    generated_at: datetime | None = None,
    requested_period_label: str | None = None,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Relatório FIDC IME",
    )
    styles = _build_styles()
    story = _build_story(
        dashboard,
        styles,
        generated_at or datetime.now(),
        requested_period_label=requested_period_label,
    )

    def draw_footer(canvas, document) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6c757d"))
        footer = f"{_fund_title(dashboard)} · {dashboard.latest_competencia}"
        canvas.drawString(LEFT_MARGIN, 7 * mm, _truncate(footer, 120))
        canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 7 * mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


def build_dashboard_pdf_file(
    dashboard: FundonetDashboardData,
    output_path: Path,
    *,
    generated_at: datetime | None = None,
) -> Path:
    output_path.write_bytes(build_dashboard_pdf_bytes(dashboard, generated_at=generated_at))
    return output_path


def _build_story(
    dashboard: FundonetDashboardData,
    styles: dict[str, ParagraphStyle],
    generated_at: datetime,
    *,
    requested_period_label: str | None = None,
) -> list[object]:
    info = dashboard.fund_info
    summary = dashboard.summary
    loaded_period = info.get("periodo_analisado")
    story: list[object] = [
        Paragraph("tomaconta FIDCs - Relatório CVM", styles["title"]),
        Paragraph(_fund_title(dashboard), styles["subtitle"]),
        Spacer(1, 3 * mm),
        _meta_table(
            [
                ("Última competência", info.get("ultima_competencia")),
                ("Período carregado", loaded_period),
                (
                    "Período solicitado",
                    requested_period_label if requested_period_label and requested_period_label != loaded_period else "Igual ao período carregado",
                ),
                ("Estrutura subordinada", info.get("estrutura_subordinada")),
                ("Cotistas", info.get("total_cotistas")),
                ("CNPJ fundo", _format_cnpj(info.get("cnpj_fundo", ""))),
                ("CNPJ classe", _format_cnpj(info.get("cnpj_classe", ""))),
                (
                    "Administrador",
                    _format_participant(
                        info.get("nome_administrador") or info.get("nm_admin"),
                        info.get("cnpj_administrador") or info.get("cnpj_admin_cadastro"),
                    ),
                ),
                (
                    "Gestor",
                    _format_participant(info.get("nome_gestor") or info.get("nm_gestor"), info.get("cnpj_gestor")),
                ),
                (
                    "Custodiante",
                    _format_participant(
                        info.get("nome_custodiante") or info.get("nm_custodiante"),
                        info.get("cnpj_custodiante"),
                    ),
                ),
                ("Condomínio", info.get("condominio")),
                ("Classe única", info.get("classe_unica")),
                ("Gerado em", generated_at.strftime("%d/%m/%Y %H:%M")),
            ],
            styles,
        ),
        Spacer(1, 5 * mm),
        _section("Radar de Risco", styles),
        _metric_table(
            [
                ("Subordinação reportada", _format_percent(summary.get("subordinacao_pct")), "PL mezzanino + subordinada residual / PL total"),
                ("Inadimplência observada", _format_percent(summary.get("inadimplencia_pct")), "Inadimplência observada (IME) / DCs"),
                ("Alocação", _format_percent(summary.get("alocacao_pct")), "Direitos creditórios / carteira"),
                ("Liquidez até 30 dias", _format_percent(_safe_pct(summary.get("liquidez_30"), summary.get("pl_total"))), "Liquidez até 30d / PL"),
                ("Liquidez imediata", _format_percent(_safe_pct(summary.get("liquidez_imediata"), summary.get("pl_total"))), "Liquidez imediata / PL"),
                ("Resgate solicitado", _format_percent(_safe_pct(summary.get("resgate_solicitado_mes"), summary.get("pl_total"))), "Resgate solicitado / PL"),
                ("PL total", _format_brl_compact(summary.get("pl_total")), "Sênior + mezzanino + subordinada"),
                ("Direitos creditórios", _format_brl_compact(summary.get("direitos_creditorios")), "DICRED"),
                ("Camadas críticas fora do IME", _display(len(dashboard.coverage_gap_df)), "Cobertura, reservas, gatilhos, rating e lastro"),
            ],
            styles,
        ),
        Spacer(1, 5 * mm),
        _section("Risco de Crédito", styles),
        _dataframe_table(
            _format_risk_metrics_table(dashboard.risk_metrics_df, "Risco de crédito"),
            styles,
            widths=[38 * mm, 22 * mm, 22 * mm, 36 * mm, 80 * mm, 34 * mm],
        ),
        Spacer(1, 4 * mm),
        _dataframe_table(
            _format_value_percent_table(dashboard.segment_latest_df, "segmento", "Segmento"),
            styles,
            widths=[70 * mm, 42 * mm, 24 * mm],
            empty_message="Sem segmentação positiva reportada.",
        ),
        Spacer(1, 4 * mm),
        _dataframe_table(
            _format_status_value_table(dashboard.default_buckets_latest_df, "faixa", "Aging inadimplência"),
            styles,
            widths=[46 * mm, 42 * mm, 42 * mm],
        ),
        Spacer(1, 5 * mm),
        _section("Risco Estrutural", styles),
        _dataframe_table(
            _format_risk_metrics_table(dashboard.risk_metrics_df, "Risco estrutural"),
            styles,
            widths=[38 * mm, 22 * mm, 22 * mm, 36 * mm, 80 * mm, 34 * mm],
        ),
        Spacer(1, 4 * mm),
        _dataframe_table(
            _format_performance_benchmark_table(dashboard.performance_vs_benchmark_latest_df),
            styles,
            widths=[56 * mm, 30 * mm, 30 * mm, 26 * mm],
            empty_message="Sem benchmark x realizado reportado no bloco DESEMP.",
        ),
        Spacer(1, 5 * mm),
        _section("Risco de Liquidez e Funding", styles),
        _dataframe_table(
            _format_risk_metrics_table(dashboard.risk_metrics_df, "Risco de liquidez"),
            styles,
            widths=[38 * mm, 22 * mm, 22 * mm, 36 * mm, 80 * mm, 34 * mm],
        ),
        Spacer(1, 4 * mm),
        _dataframe_table(
            _format_event_summary_table(dashboard.event_summary_latest_df),
            styles,
            widths=[36 * mm, 34 * mm, 34 * mm, 24 * mm, 32 * mm, 93 * mm],
        ),
        Spacer(1, 4 * mm),
        _dataframe_table(
            _format_status_value_table(dashboard.maturity_latest_df, "faixa", "Prazo de vencimento"),
            styles,
            widths=[46 * mm, 42 * mm, 42 * mm],
        ),
        Spacer(1, 4 * mm),
        _dataframe_table(
            _format_latest_quota_table(dashboard.quota_pl_history_df, dashboard.latest_competencia),
            styles,
            widths=[58 * mm, 34 * mm, 34 * mm, 38 * mm, 42 * mm],
            empty_message="Sem quadro de cotas para a competência mais recente.",
        ),
        Spacer(1, 5 * mm),
        _section("Risco Operacional e Contratual", styles),
        _dataframe_table(
            _format_coverage_gap_table(dashboard.coverage_gap_df),
            styles,
            widths=[42 * mm, 32 * mm, 90 * mm, 70 * mm],
        ),
        Spacer(1, 5 * mm),
        _dataframe_table(
            _format_glossary_table(dashboard.mini_glossary_df),
            styles,
            widths=[42 * mm, 190 * mm],
        ),
        Spacer(1, 5 * mm),
        _section("Tabelas CVM Normalizadas", styles),
        _dataframe_table(
            _format_tracking_table(dashboard.tracking_latest_df),
            styles,
            widths=[52 * mm, 34 * mm, 36 * mm, 90 * mm, 42 * mm],
        ),
        Spacer(1, 5 * mm),
        _section("Notas Metodológicas", styles),
        _notes_table(dashboard.methodology_notes, styles),
    ]

    if not dashboard.holder_latest_df.empty:
        story.extend(
            [
                Spacer(1, 5 * mm),
                _section("Cotistas", styles),
                _dataframe_table(
                    _format_holder_table(dashboard.holder_latest_df),
                    styles,
                    widths=[45 * mm, 78 * mm, 34 * mm],
                ),
            ]
        )
    if not dashboard.rate_negotiation_latest_df.empty:
        story.extend(
            [
                Spacer(1, 5 * mm),
                _section("Taxas de Negociação", styles),
                _dataframe_table(
                    _format_rate_table(dashboard.rate_negotiation_latest_df),
                    styles,
                    widths=[52 * mm, 58 * mm, 28 * mm, 28 * mm, 28 * mm],
                ),
            ]
        )
    return story


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "FidcTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#223247"),
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "FidcSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#566270"),
        ),
        "section": ParagraphStyle(
            "FidcSection",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#ff5a00"),
            spaceBefore=3,
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "FidcCell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=9,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#2f3a48"),
        ),
        "cell_right": ParagraphStyle(
            "FidcCellRight",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=9,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#2f3a48"),
        ),
        "header": ParagraphStyle(
            "FidcHeaderCell",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.0,
            leading=8.5,
            alignment=TA_LEFT,
            textColor=colors.white,
        ),
        "metric_label": ParagraphStyle(
            "FidcMetricLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=6.5,
            leading=8,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#566270"),
        ),
        "metric_value": ParagraphStyle(
            "FidcMetricValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#223247"),
        ),
        "metric_source": ParagraphStyle(
            "FidcMetricSource",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=6,
            leading=7,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#8a96a3"),
        ),
    }


def _section(title: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_escape(title.upper()), styles["section"])


def _meta_table(items: Iterable[tuple[str, object]], styles: dict[str, ParagraphStyle]) -> Table:
    row: list[object] = []
    rows: list[list[object]] = []
    for label, value in items:
        row.append(Paragraph(f"<b>{_escape(label)}:</b> {_escape(_display(value))}", styles["cell"]))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        row.extend([""] * (4 - len(row)))
        rows.append(row)
    table = Table(rows, colWidths=[CONTENT_WIDTH / 4] * 4)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#dfe6ee")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#edf2f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _metric_table(items: Iterable[tuple[str, str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    cells: list[object] = []
    rows: list[list[object]] = []
    for label, value, source in items:
        cell = [
            Paragraph(_escape(label.upper()), styles["metric_label"]),
            Paragraph(_escape(value), styles["metric_value"]),
            Paragraph(_escape(source), styles["metric_source"]),
        ]
        cells.append(Table([[cell[0]], [cell[1]], [cell[2]]], colWidths=[CONTENT_WIDTH / 4 - 2 * mm]))
        if len(cells) == 4:
            rows.append(cells)
            cells = []
    if cells:
        cells.extend([""] * (4 - len(cells)))
        rows.append(cells)
    table = Table(rows, colWidths=[CONTENT_WIDTH / 4] * 4)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#dfe6ee")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#edf2f7")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _dataframe_table(
    df: pd.DataFrame,
    styles: dict[str, ParagraphStyle],
    *,
    widths: list[float] | None = None,
    empty_message: str = "Sem dados reportados.",
) -> Table:
    if df.empty:
        df = pd.DataFrame({"Observação": [empty_message]})
    columns = list(df.columns)
    if widths is None:
        widths = [CONTENT_WIDTH / max(1, len(columns))] * len(columns)
    data: list[list[object]] = [[Paragraph(_escape(column), styles["header"]) for column in columns]]
    numeric_names = {"valor", "valor bruto", "sinal econômico", "%", "% pl", "mês", "ano", "12 meses", "quantidade", "pl"}
    for _, row in df.iterrows():
        cells: list[object] = []
        for column in columns:
            style = styles["cell_right"] if str(column).strip().lower() in numeric_names else styles["cell"]
            cells.append(Paragraph(_escape(_display(row.get(column))), style))
        data.append(cells)

    table = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111111")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#dfe6ee")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#edf2f7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _notes_table(notes: list[str], styles: dict[str, ParagraphStyle]) -> Table:
    rows = [{"Nota": note} for note in notes]
    return _dataframe_table(pd.DataFrame(rows), styles, widths=[CONTENT_WIDTH])


def _format_value_percent_table(df: pd.DataFrame, label_column: str, label_title: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[label_title, "Valor", "%"])
    output = df.copy()
    output[label_title] = output[label_column]
    output["Valor"] = output["valor"].map(_format_brl_compact)
    output["%"] = output["percentual"].map(_format_percent) if "percentual" in output.columns else "N/D"
    return output[[label_title, "Valor", "%"]]


def _format_status_value_table(df: pd.DataFrame, label_column: str, label_title: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[label_title, "Valor", "Status da fonte"])
    output = df.sort_values("ordem").copy() if "ordem" in df.columns else df.copy()
    output[label_title] = output[label_column]
    output["Valor"] = output.apply(_format_status_value_row, axis=1)
    output["Status da fonte"] = output["source_status"].map(_status_label)
    return output[[label_title, "Valor", "Status da fonte"]]


def _format_status_value_row(row: pd.Series) -> str:
    status = str(row.get("source_status", "reported_value"))
    raw_value = row.get("valor_raw", row.get("valor"))
    if status in {"missing_field", "not_reported", "not_numeric", "not_available"} and _is_missing(raw_value):
        return "N/D"
    return _format_brl_compact(row.get("valor"))


def _format_event_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Evento", "Valor bruto", "Sinal econômico", "% PL", "Status", "Leitura"])
    output = df.sort_values("ordem").copy() if "ordem" in df.columns else df.copy()
    output["Evento"] = output["evento"]
    output["Valor bruto"] = output["valor_total"].map(_format_brl_compact)
    output["Sinal econômico"] = output["valor_total_assinado"].map(_format_brl_compact)
    output["% PL"] = output["valor_total_pct_pl"].map(_format_percent)
    output["Status"] = output["source_status"].map(_status_label)
    output["Leitura"] = output["interpretação"]
    return output[["Evento", "Valor bruto", "Sinal econômico", "% PL", "Status", "Leitura"]]


def _class_display_column(df: pd.DataFrame) -> str:
    if "class_label" in df.columns:
        return "class_label"
    return "label"


def _format_return_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Classe", "Mês", "Ano", "12 Meses"])
    output = df.copy()
    output["Classe"] = output[_class_display_column(output)]
    output["Mês"] = output["retorno_mes_pct"].map(_format_percent)
    output["Ano"] = output["retorno_ano_pct"].map(_format_percent)
    output["12 Meses"] = output["retorno_12m_pct"].map(_format_percent)
    return output[["Classe", "Mês", "Ano", "12 Meses"]]


def _format_performance_benchmark_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Classe", "Benchmark", "Realizado", "Gap (bps)"])
    output = df.copy()
    output["Classe"] = output[_class_display_column(output)]
    output["Benchmark"] = output["desempenho_esperado_pct"].map(_format_percent)
    output["Realizado"] = output["desempenho_real_pct"].map(_format_percent)
    output["Gap (bps)"] = output["gap_bps"].map(lambda value: _format_decimal(value, decimals=0))
    return output[["Classe", "Benchmark", "Realizado", "Gap (bps)"]]


def _format_latest_quota_table(df: pd.DataFrame, latest_competencia: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Classe", "Tipo", "Qt. cotas", "Valor da cota", "PL"])
    latest_df = df[df["competencia"] == latest_competencia].copy()
    if latest_df.empty:
        return pd.DataFrame(columns=["Classe", "Tipo", "Qt. cotas", "Valor da cota", "PL"])
    if "aggregation_scope" in latest_df.columns and latest_df["aggregation_scope"].eq("portfolio").all():
        latest_df["Classe"] = latest_df["class_macro_label"].fillna(latest_df[_class_display_column(latest_df)])
        latest_df["PL"] = latest_df["pl"].map(_format_brl_compact)
        latest_df["% do PL"] = latest_df["pl_share_pct"].map(_format_percent)
        return latest_df[["Classe", "PL", "% do PL"]]
    latest_df["Classe"] = latest_df[_class_display_column(latest_df)]
    latest_df["Tipo"] = latest_df.get("class_macro_label", latest_df["class_kind"])
    latest_df["Qt. cotas"] = latest_df["qt_cotas"].map(lambda value: _format_decimal(value, decimals=4))
    latest_df["Valor da cota"] = latest_df["vl_cota"].map(_format_brl)
    latest_df["PL"] = latest_df["pl"].map(_format_brl_compact)
    return latest_df[["Classe", "Tipo", "Qt. cotas", "Valor da cota", "PL"]]


def _format_tracking_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Indicador", "Valor", "Fonte", "Interpretação", "Estado"])
    output = df.copy()
    output["Indicador"] = output["indicador"]
    output["Valor"] = output.apply(_format_tracking_value, axis=1)
    output["Fonte"] = output["fonte"]
    output["Interpretação"] = output["interpretação"]
    output["Estado"] = output["estado_dado"].map(_data_state_label) if "estado_dado" in output.columns else "Calculado"
    return output[["Indicador", "Valor", "Fonte", "Interpretação", "Estado"]]


def _format_holder_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Grupo", "Categoria", "Quantidade"])
    output = df.copy()
    output["Grupo"] = output["grupo"]
    output["Categoria"] = output["categoria"]
    output["Quantidade"] = output["quantidade"].map(lambda value: _format_decimal(value, decimals=0))
    return output[["Grupo", "Categoria", "Quantidade"]]


def _format_rate_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Grupo", "Operação", "Mín.", "Média", "Máx."])
    output = df.copy()
    output["Grupo"] = output["grupo"]
    output["Operação"] = output["operacao"]
    output["Mín."] = output["taxa_min"].map(_format_percent)
    output["Média"] = output["taxa_media"].map(_format_percent)
    output["Máx."] = output["taxa_max"].map(_format_percent)
    return output[["Grupo", "Operação", "Mín.", "Média", "Máx."]]


def _format_tracking_value(row: pd.Series) -> str:
    if row.get("estado_dado") == "nao_aplicavel_sem_inadimplencia":
        return "N/A (sem inadimplência)"
    if row.get("estado_dado") == "nao_disponivel_na_fonte":
        return "N/D"
    if row.get("unidade") == "%":
        return _format_percent(row.get("valor"))
    return _format_decimal(row.get("valor"))


def _format_metric_value(value: object, unit: str) -> str:
    if unit == "R$":
        return _format_brl_compact(value)
    if unit == "%":
        return _format_percent(value)
    return _format_decimal(value)


def _metric_criticality_label(value: object) -> str:
    labels = {
        "critico": "Crítico",
        "monitorar": "Monitorar",
        "contexto": "Contexto",
    }
    return labels.get(str(value), _display(value))


def _risk_metric_state_label(value: object) -> str:
    labels = {
        "calculado": "Calculado",
        "nao_calculavel": "Não calculável",
        "nao_calculavel_sem_pl": "Não calc.: sem PL",
        "nao_aplicavel_sem_inadimplencia": "N/A sem inadimplência",
        "nao_disponivel_na_fonte": "Não disponível na fonte",
        "nao_calculavel_sem_base": "Não calc.: sem base",
        "exige_fonte_complementar": "Exige fonte complementar",
    }
    return labels.get(str(value), _display(value))


def _format_risk_metrics_table(df: pd.DataFrame, risk_block: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Métrica", "Valor", "Criticidade", "Fonte", "Leitura", "Estado"])
    output = df[df["risk_block"] == risk_block].copy()
    if output.empty:
        return pd.DataFrame(columns=["Métrica", "Valor", "Criticidade", "Fonte", "Leitura", "Estado"])
    output["Métrica"] = output["label"]
    output["Valor"] = output.apply(
        lambda row: _format_metric_value(row.get("value"), str(row.get("unit") or "")),
        axis=1,
    )
    output["Criticidade"] = output["criticality"].map(_metric_criticality_label)
    output["Fonte"] = output["source_data"]
    output["Leitura"] = output["interpretation"]
    output["Estado"] = output["state"].map(_risk_metric_state_label)
    return output[["Métrica", "Valor", "Criticidade", "Fonte", "Leitura", "Estado"]]


def _format_coverage_gap_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Tema", "Status", "Por que importa", "Fonte necessária"])
    output = df.copy()
    output["Tema"] = output["tema"]
    output["Status"] = output["status"]
    output["Por que importa"] = output["por_que_importa"]
    output["Fonte necessária"] = output["fonte_necessaria"]
    return output[["Tema", "Status", "Por que importa", "Fonte necessária"]]


def _format_glossary_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Termo", "Definição"])
    output = df.copy()
    output["Termo"] = output["termo"]
    output["Definição"] = output.get("definicao_curta", output.get("definicao", "N/D"))
    return output[["Termo", "Definição"]]


def _status_label(value: object) -> str:
    labels = {
        "reported_value": "Valor reportado",
        "reported_zero": "Zero reportado",
        "missing_field": "Campo ausente",
        "not_reported": "Não informado",
        "not_numeric": "Valor não numérico",
        "not_available": "Não disponível",
    }
    return labels.get(str(value), _display(value))


def _data_state_label(value: object) -> str:
    labels = {
        "calculado": "Calculado",
        "nao_calculavel": "Não calculável",
        "nao_calculavel_sem_pl": "Não calculável: sem PL",
        "nao_aplicavel_sem_inadimplencia": "Não aplicável: sem inadimplência",
        "nao_disponivel_na_fonte": "Não disponível na fonte",
    }
    return labels.get(str(value), _display(value))


def _fund_title(dashboard: FundonetDashboardData) -> str:
    info = dashboard.fund_info
    return str(info.get("nome_fundo") or info.get("nome_classe") or "FIDC selecionado")


def _display(value: object) -> str:
    if _is_missing(value):
        return "N/D"
    return str(value)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _format_decimal(value: object, decimals: int = 2) -> str:
    if _is_missing(value):
        return "N/D"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/D"
    if numeric == 0:
        numeric = 0.0
    formatted = f"{numeric:,.{decimals}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_percent(value: object) -> str:
    if _is_missing(value):
        return "N/D"
    return f"{_format_decimal(value, decimals=2)}%"


def _format_brl(value: object) -> str:
    if _is_missing(value):
        return "N/D"
    return f"R$ {_format_decimal(value, decimals=2)}"


def _format_brl_compact(value: object) -> str:
    if _is_missing(value):
        return "N/D"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/D"
    magnitude = abs(numeric)
    if magnitude >= 1_000_000_000:
        return f"R$ {_format_decimal(numeric / 1_000_000_000, decimals=2)} bi"
    if magnitude >= 1_000_000:
        return f"R$ {_format_decimal(numeric / 1_000_000, decimals=1)} mi"
    if magnitude >= 1_000:
        return f"R$ {_format_decimal(numeric / 1_000, decimals=1)} mil"
    return f"R$ {_format_decimal(numeric, decimals=2)}"


def _format_cnpj(value: str) -> str:
    return format_cnpj(value)


def _format_participant(name: object, cnpj: object) -> str:
    name_text = str(name or "").strip()
    cnpj_text = _format_cnpj(str(cnpj or ""))
    if name_text and cnpj_text != "N/D":
        return f"{name_text} · {cnpj_text}"
    if name_text:
        return name_text
    return cnpj_text


def _safe_pct(numerator: object, denominator: object) -> float | None:
    if _is_missing(numerator) or _is_missing(denominator):
        return None
    try:
        num = float(numerator)
        den = float(denominator)
    except (TypeError, ValueError):
        return None
    if den <= 0:
        return None
    return num / den * 100.0


def _escape(value: object) -> str:
    text = _display(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."
