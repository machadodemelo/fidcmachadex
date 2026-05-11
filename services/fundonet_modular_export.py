"""Exportação modular por seção — gera PDFs executivos independentes por bloco.

Cada função retorna bytes de um PDF pronto para download / apresentação.
O layout segue o padrão das imagens de referência:
  - Título executivo com nome do fundo
  - Tabela(s) de dados do bloco
  - Rodapé com fonte e competência
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

if TYPE_CHECKING:
    from services.fundonet_dashboard import FundonetDashboardData

PAGE_SIZE = landscape(A4)
PAGE_WIDTH = PAGE_SIZE[0]
LEFT_MARGIN = 14 * mm
RIGHT_MARGIN = 14 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

_BRAND_ORANGE = "#ff5a00"
_BRAND_DARK = "#111111"
_BRAND_NAVY = "#223247"
_GRAY = "#6c757d"
_LIGHT_BG = "#f8fafc"
_BORDER = "#dfe6ee"


# ---------------------------------------------------------------------------
# Public API — one function per exportable block
# ---------------------------------------------------------------------------

def build_subordination_pdf_bytes(dashboard: "FundonetDashboardData") -> bytes:
    """Bloco: Subordinação reportada + PL por tipo de cota."""
    story = _base_story(dashboard, "Subordinação Reportada e Estrutura de Cotas")
    story += _section_header("Subordinação Reportada (IME) — Histórico")
    story += [_kv_table(dashboard.subordination_history_df, value_col="subordinacao_pct", pct=True)]
    story += _section_header("PL por Tipo de Cota — Última Competência")
    story += [_quota_table(dashboard.quota_pl_history_df, dashboard.latest_competencia)]
    story += _fonte_nota("Fonte: Informe Mensal CVM — bloco COTA_CLASSE / PL subordinado / PL total.")
    return _build_pdf(story, dashboard)


def build_pl_pdf_bytes(dashboard: "FundonetDashboardData") -> bytes:
    """Bloco: Patrimônio Líquido — evolução histórica."""
    story = _base_story(dashboard, "Patrimônio Líquido")
    story += _section_header("Evolução do PL — Histórico")
    story += [_asset_history_table(dashboard.asset_history_df)]
    story += _fonte_nota("Fonte: Informe Mensal CVM — APLIC_ATIVO/VL_SOM_APLIC_ATIVO; PL total das cotas.")
    return _build_pdf(story, dashboard)


def build_rentabilidade_pdf_bytes(dashboard: "FundonetDashboardData") -> bytes:
    """Bloco: Rentabilidade mensal por tipo de cota."""
    story = _base_story(dashboard, "Rentabilidade Mensal por Cota")
    story += _section_header("Retorno Mensal por Classe de Cota")
    story += [_return_table(dashboard.return_history_df)]
    if not dashboard.performance_vs_benchmark_latest_df.empty:
        story += _section_header("Benchmark × Realizado — Última Competência")
        story += [_benchmark_table(dashboard.performance_vs_benchmark_latest_df)]
    story += _fonte_nota("Fonte: Informe Mensal CVM — RENT_MES/PR_APURADA; DESEMP usado como validação e benchmark.")
    return _build_pdf(story, dashboard)


def build_npl_pdf_bytes(dashboard: "FundonetDashboardData") -> bytes:
    """Bloco: Inadimplência, provisão e cobertura."""
    story = _base_story(dashboard, "Inadimplência e Cobertura")
    story += _section_header("Histórico de Inadimplência e Provisão")
    story += [_default_history_table(dashboard.default_history_df)]
    story += _section_header(f"Aging da Inadimplência — {dashboard.latest_competencia}")
    story += [_aging_table(dashboard.default_buckets_latest_df)]
    story += _fonte_nota("Fonte: Informe Mensal CVM — CRED_EXISTE/DICRED aging; provisão redução/recuperação.")
    return _build_pdf(story, dashboard)


def build_vencimento_pdf_bytes(dashboard: "FundonetDashboardData") -> bytes:
    """Bloco: Vencimento dos direitos creditórios + duration estimada."""
    story = _base_story(dashboard, "Vencimento e Duration Estimada dos Recebíveis")
    story += _section_header(f"Distribuição por Prazo — {dashboard.latest_competencia}")
    story += [_maturity_table(dashboard.maturity_latest_df)]
    if not dashboard.duration_history_df.empty:
        story += _section_header("Duration Estimada — Evolução Mensal (dias)")
        story += [_duration_table(dashboard.duration_history_df)]
        story += _fonte_nota(
            "Duration = Σ(saldo_bucket × prazo_proxy) / Σ(saldo_bucket). "
            "Proxies: Vencidos=0d; ≤30d=30d; intervalos=ponto médio; "
            ">1080d só entra se a faixa aberta não dominar a carteira. "
            "Fonte: COMPMT_DICRED_AQUIS / SEM_AQUIS — Informe Mensal CVM."
        )
    else:
        story += _fonte_nota("Fonte: COMPMT_DICRED_AQUIS / SEM_AQUIS — Informe Mensal CVM.")
    return _build_pdf(story, dashboard)


def build_radar_pdf_bytes(dashboard: "FundonetDashboardData") -> bytes:
    """Bloco: Radar de risco — visão executiva completa."""
    story = _base_story(dashboard, "Radar de Risco — Visão Executiva")
    story += _section_header("Métricas de Crédito")
    story += [_risk_block_table(dashboard.risk_metrics_df, "Risco de crédito")]
    story += _section_header("Métricas Estruturais")
    story += [_risk_block_table(dashboard.risk_metrics_df, "Risco estrutural")]
    story += _section_header("Métricas de Liquidez")
    story += [_risk_block_table(dashboard.risk_metrics_df, "Risco de liquidez")]
    story += _fonte_nota("Fonte: Informe Mensal CVM — calculado pelo TomaContaFIDCs.")
    return _build_pdf(story, dashboard)


# ---------------------------------------------------------------------------
# Story building helpers
# ---------------------------------------------------------------------------

def _build_pdf(story: list, dashboard: "FundonetDashboardData") -> bytes:
    buffer = BytesIO()
    styles = _styles()
    fund_title = _fund_title(dashboard)
    competencia = dashboard.latest_competencia

    def footer(canvas, doc):  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor(_GRAY))
        canvas.drawString(LEFT_MARGIN, 7 * mm, _trunc(f"{fund_title} · {competencia}", 110))
        canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 7 * mm, f"Pág. {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _base_story(dashboard: "FundonetDashboardData", block_title: str) -> list:
    styles = _styles()
    fund_title = _fund_title(dashboard)
    info = dashboard.fund_info
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    meta_items = [
        ("Fundo", fund_title),
        ("CNPJ", _fmt_cnpj(info.get("cnpj_fundo", ""))),
        ("Competência", dashboard.latest_competencia),
        ("Gerado em", generated),
    ]
    return [
        Paragraph("TomaContaFIDCs", styles["brand"]),
        Paragraph(block_title, styles["title"]),
        Spacer(1, 3 * mm),
        _meta_row(meta_items, styles),
        Spacer(1, 5 * mm),
    ]


def _section_header(text: str) -> list:
    styles = _styles()
    return [Paragraph(_esc(text.upper()), styles["section"]), Spacer(1, 1 * mm)]


def _fonte_nota(text: str) -> list:
    styles = _styles()
    return [Spacer(1, 4 * mm), Paragraph(_esc(text), styles["fonte"])]


# ---------------------------------------------------------------------------
# Data table builders
# ---------------------------------------------------------------------------

def _meta_row(items: list[tuple[str, str]], styles: dict) -> Table:
    cells = [Paragraph(f"<b>{_esc(k)}:</b> {_esc(str(v or 'N/D'))}", styles["cell"]) for k, v in items]
    while len(cells) % 4 != 0:
        cells.append(Paragraph("", styles["cell"]))
    rows = [cells[i:i+4] for i in range(0, len(cells), 4)]
    t = Table(rows, colWidths=[CONTENT_WIDTH / 4] * 4)
    t.setStyle(_meta_style())
    return t


def _df_table(df: pd.DataFrame, styles: dict, *, col_widths: list[float] | None = None, empty_msg: str = "Sem dados.") -> Table:
    if df.empty:
        df = pd.DataFrame({"Observação": [empty_msg]})
    cols = list(df.columns)
    if col_widths is None:
        col_widths = [CONTENT_WIDTH / len(cols)] * len(cols)
    numeric_cols = {"valor", "valor bruto", "%", "% pl", "mês", "ano", "12 meses", "duration (dias)", "saldo total"}
    header_row = [Paragraph(_esc(c), styles["header"]) for c in cols]
    data_rows = []
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            style = styles["cell_r"] if str(c).strip().lower() in numeric_cols else styles["cell"]
            cells.append(Paragraph(_esc(_disp(row.get(c))), style))
        data_rows.append(cells)
    t = Table([header_row] + data_rows, colWidths=col_widths, repeatRows=1, splitByRow=1)
    t.setStyle(_data_style())
    return t


def _kv_table(df: pd.DataFrame, *, value_col: str, pct: bool = False) -> Table:
    styles = _styles()
    if df.empty or "competencia" not in df.columns or value_col not in df.columns:
        return _df_table(pd.DataFrame(), styles)
    out = df[["competencia", value_col]].copy()
    out.columns = ["Competência", "Valor (%)"] if pct else ["Competência", "Valor"]
    if pct:
        out["Valor (%)"] = pd.to_numeric(out["Valor (%)"], errors="coerce").map(
            lambda v: f"{v:.2f}%".replace(".", ",") if pd.notna(v) else "N/D"
        )
    return _df_table(out, styles, col_widths=[60 * mm, 60 * mm])


def _quota_table(quota_df: pd.DataFrame, latest_competencia: str) -> Table:
    styles = _styles()
    if quota_df.empty:
        return _df_table(pd.DataFrame(), styles)
    df = quota_df[quota_df["competencia"] == latest_competencia].copy()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    if "aggregation_scope" in df.columns and df["aggregation_scope"].eq("portfolio").all():
        df["Classe"] = df.get("class_macro_label", df[_class_display_column(df)])
        df["PL"] = df["pl"].map(_fmt_brl_compact)
        out = df[["Classe", "PL"]].copy()
        return _df_table(out, styles, col_widths=[90 * mm, 50 * mm])
    df["Classe"] = df[_class_display_column(df)]
    df["Tipo"] = df.get("class_macro_label", df["class_kind"])
    df["PL"] = df["pl"].map(_fmt_brl_compact)
    df["% PL"] = pd.to_numeric(df.get("pl_pct", pd.Series(dtype=float)), errors="coerce").map(
        lambda v: f"{v:.1f}%".replace(".", ",") if pd.notna(v) else "N/D"
    )
    out = df[["Classe", "Tipo", "PL"]].copy()
    return _df_table(out, styles, col_widths=[90 * mm, 50 * mm, 50 * mm])


def _class_display_column(df: pd.DataFrame) -> str:
    if "class_label" in df.columns:
        return "class_label"
    return "label"


def _asset_history_table(df: pd.DataFrame) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    cols = [c for c in ["competencia", "ativos_totais", "carteira", "direitos_creditorios", "pl_total"] if c in df.columns]
    out = df[cols].copy()
    labels = {"competencia": "Competência", "ativos_totais": "Ativo Total", "carteira": "Carteira",
              "direitos_creditorios": "Dir. Creditórios", "pl_total": "PL Total"}
    out = out.rename(columns=labels)
    for c in ["Ativo Total", "Carteira", "Dir. Creditórios", "PL Total"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").map(_fmt_brl_compact)
    return _df_table(out, styles)


def _return_table(df: pd.DataFrame) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    label_column = _class_display_column(df)
    cols = [c for c in ["competencia", label_column, "retorno_mes_pct"] if c in df.columns]
    out = df[cols].copy()
    out = out.rename(columns={"competencia": "Competência", label_column: "Classe", "retorno_mes_pct": "Retorno Mês (%)"})
    if "Retorno Mês (%)" in out.columns:
        out["Retorno Mês (%)"] = pd.to_numeric(out["Retorno Mês (%)"], errors="coerce").map(
            lambda v: f"{v:.2f}%".replace(".", ",") if pd.notna(v) else "N/D"
        )
    return _df_table(out, styles)


def _benchmark_table(df: pd.DataFrame) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    out = df.copy()
    out["Classe"] = out.get(_class_display_column(out), "")
    out["Benchmark"] = pd.to_numeric(out.get("desempenho_esperado_pct"), errors="coerce").map(
        lambda v: f"{v:.2f}%".replace(".", ",") if pd.notna(v) else "N/D"
    )
    out["Realizado"] = pd.to_numeric(out.get("desempenho_real_pct"), errors="coerce").map(
        lambda v: f"{v:.2f}%".replace(".", ",") if pd.notna(v) else "N/D"
    )
    return _df_table(out[["Classe", "Benchmark", "Realizado"]], styles, col_widths=[80 * mm, 50 * mm, 50 * mm])


def _default_history_table(df: pd.DataFrame) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    cols = [c for c in ["competencia", "inadimplencia_total", "provisao_total", "inadimplencia_pct"] if c in df.columns]
    out = df[cols].copy()
    labels = {"competencia": "Competência", "inadimplencia_total": "Inadimplência (R$)",
              "provisao_total": "Provisão (R$)", "inadimplencia_pct": "Inad. (%)"}
    out = out.rename(columns=labels)
    for c in ["Inadimplência (R$)", "Provisão (R$)"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").map(_fmt_brl_compact)
    if "Inad. (%)" in out.columns:
        out["Inad. (%)"] = pd.to_numeric(out["Inad. (%)"], errors="coerce").map(
            lambda v: f"{v:.2f}%".replace(".", ",") if pd.notna(v) else "N/D"
        )
    return _df_table(out, styles)


def _aging_table(df: pd.DataFrame) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    out = df[["faixa", "valor"]].copy() if "faixa" in df.columns else pd.DataFrame()
    if out.empty:
        return _df_table(pd.DataFrame(), styles)
    out = out.rename(columns={"faixa": "Faixa de Vencimento", "valor": "Saldo (R$)"})
    out["Saldo (R$)"] = pd.to_numeric(out["Saldo (R$)"], errors="coerce").map(_fmt_brl_compact)
    return _df_table(out, styles, col_widths=[100 * mm, 70 * mm])


def _maturity_table(df: pd.DataFrame) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    out = df[["faixa", "valor"]].copy() if "faixa" in df.columns else pd.DataFrame()
    if out.empty:
        return _df_table(pd.DataFrame(), styles)
    total = pd.to_numeric(out["valor"], errors="coerce").sum()
    out = out.rename(columns={"faixa": "Prazo de Vencimento", "valor": "Saldo (R$)"})
    out["Saldo (R$)"] = pd.to_numeric(out["Saldo (R$)"], errors="coerce").map(_fmt_brl_compact)
    out["% Carteira"] = pd.to_numeric(df["valor"], errors="coerce").map(
        lambda v: f"{v / total * 100:.1f}%".replace(".", ",") if total > 0 and pd.notna(v) else "N/D"
    )
    return _df_table(out, styles, col_widths=[90 * mm, 60 * mm, 40 * mm])


def _duration_table(df: pd.DataFrame) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    ok = df[df["data_quality"] == "ok"].copy()
    if ok.empty:
        return _df_table(pd.DataFrame(), styles)
    out = ok[["competencia", "duration_days", "total_saldo"]].copy()
    out = out.rename(columns={"competencia": "Competência", "duration_days": "Duration (dias)", "total_saldo": "Saldo Total"})
    out["Duration (dias)"] = pd.to_numeric(out["Duration (dias)"], errors="coerce").map(
        lambda v: f"{v:.0f}" if pd.notna(v) else "N/D"
    )
    out["Saldo Total"] = pd.to_numeric(out["Saldo Total"], errors="coerce").map(_fmt_brl_compact)
    return _df_table(out, styles, col_widths=[60 * mm, 60 * mm, 70 * mm])


def _risk_block_table(df: pd.DataFrame, block: str) -> Table:
    styles = _styles()
    if df.empty:
        return _df_table(pd.DataFrame(), styles)
    filtered = df[df["risk_block"] == block].copy()
    if filtered.empty:
        return _df_table(pd.DataFrame(), styles)
    filtered["Métrica"] = filtered["label"]
    filtered["Valor"] = filtered.apply(
        lambda r: _fmt_metric(r.get("value"), str(r.get("unit") or "")), axis=1
    )
    filtered["Leitura"] = filtered["interpretation"]
    return _df_table(filtered[["Métrica", "Valor", "Leitura"]], styles, col_widths=[70 * mm, 30 * mm, 130 * mm])


# ---------------------------------------------------------------------------
# ReportLab styles & table styles
# ---------------------------------------------------------------------------

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle("Brand", parent=base["Normal"], fontName="Helvetica",
                                fontSize=8, textColor=colors.HexColor(_BRAND_ORANGE), spaceAfter=1),
        "title": ParagraphStyle("Title", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=14, leading=17, textColor=colors.HexColor(_BRAND_NAVY),
                                alignment=TA_LEFT, spaceAfter=2),
        "section": ParagraphStyle("Section", parent=base["Heading2"], fontName="Helvetica-Bold",
                                  fontSize=9, leading=11, textColor=colors.HexColor(_BRAND_ORANGE),
                                  spaceBefore=4, spaceAfter=3),
        "cell": ParagraphStyle("Cell", parent=base["BodyText"], fontName="Helvetica",
                               fontSize=7, leading=8.5, textColor=colors.HexColor("#2f3a48")),
        "cell_r": ParagraphStyle("CellR", parent=base["BodyText"], fontName="Helvetica",
                                 fontSize=7, leading=8.5, alignment=TA_RIGHT, textColor=colors.HexColor("#2f3a48")),
        "header": ParagraphStyle("Header", parent=base["BodyText"], fontName="Helvetica-Bold",
                                 fontSize=7, leading=8.5, textColor=colors.white),
        "fonte": ParagraphStyle("Fonte", parent=base["Normal"], fontName="Helvetica",
                                fontSize=6.5, textColor=colors.HexColor(_GRAY), leading=8),
    }


def _meta_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_LIGHT_BG)),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor(_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor(_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


def _data_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_BRAND_DARK)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(_LIGHT_BG)]),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor(_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor(_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fund_title(dashboard: "FundonetDashboardData") -> str:
    info = dashboard.fund_info
    return str(info.get("nome_fundo") or info.get("nome_classe") or "FIDC")


def _fmt_brl_compact(value: object) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/D"
    if abs(v) >= 1_000_000_000:
        return f"R$ {v/1_000_000_000:.2f} bi".replace(".", ",")
    if abs(v) >= 1_000_000:
        return f"R$ {v/1_000_000:.1f} mi".replace(".", ",")
    if abs(v) >= 1_000:
        return f"R$ {v/1_000:.1f} mil".replace(".", ",")
    return f"R$ {v:.2f}".replace(".", ",")


def _fmt_metric(value: object, unit: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/D"
    if unit == "%":
        return f"{v:.2f}%".replace(".", ",")
    if unit == "R$":
        return _fmt_brl_compact(v)
    return f"{v:.2f}".replace(".", ",")


def _fmt_cnpj(value: str) -> str:
    digits = "".join(c for c in str(value or "") if c.isdigit())
    if len(digits) != 14:
        return value or "N/D"
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _disp(value: object) -> str:
    if value is None:
        return "N/D"
    try:
        if pd.isna(value):
            return "N/D"
    except (TypeError, ValueError):
        pass
    return str(value)


def _esc(value: object) -> str:
    return (
        _disp(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _trunc(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."
