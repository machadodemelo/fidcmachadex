from __future__ import annotations

import pandas as pd
import altair as alt

from services.mercado_livre_dashboard import PT_MONTH_ABBR


CORES_MELI = {
    "primaria": "#000000",
    "secundaria": "#E47811",
    "auxiliar": "#3F3F3F",
    "cinza_medio": "#8C8C8C",
    "cinza_claro": "#E5E5E5",
}

SENIOR_COLOR = CORES_MELI["primaria"]
SUB_MEZZ_COLOR = CORES_MELI["secundaria"]
SUBORDINATION_COLOR = CORES_MELI["auxiliar"]
NPL_COLOR = CORES_MELI["primaria"]
COVERAGE_COLOR = CORES_MELI["secundaria"]


def pl_subordination_chart(monthly_df: pd.DataFrame, *, title: str = "Evolução de PL e Subordinação") -> alt.Chart:
    if monthly_df.empty:
        return _empty_chart(title=title)
    df = monthly_df.sort_values("competencia_dt").copy()
    scale_divisor, scale_label = _money_scale(
        pd.concat(
            [
                pd.to_numeric(df.get("pl_senior"), errors="coerce"),
                pd.to_numeric(df.get("pl_subordinada_mezz_ex360"), errors="coerce"),
            ],
            ignore_index=True,
        )
    )
    bar_rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        bar_rows.append(
            {
                "competencia": _format_competencia(row.get("competencia_dt"), row.get("competencia")),
                "ordem": 1,
                "serie": "Sênior",
                "valor": _num(row.get("pl_senior")),
                "valor_scaled": _divide(row.get("pl_senior"), scale_divisor),
                "valor_fmt": _format_money(row.get("pl_senior"), scale_divisor=scale_divisor, scale_label=scale_label),
            }
        )
        bar_rows.append(
            {
                "competencia": _format_competencia(row.get("competencia_dt"), row.get("competencia")),
                "ordem": 2,
                "serie": "Subordinada + Mez ex-360",
                "valor": _num(row.get("pl_subordinada_mezz_ex360")),
                "valor_scaled": _divide(row.get("pl_subordinada_mezz_ex360"), scale_divisor),
                "valor_fmt": _format_money(row.get("pl_subordinada_mezz_ex360"), scale_divisor=scale_divisor, scale_label=scale_label),
            }
        )
    bar_df = pd.DataFrame(bar_rows)
    line_df = pd.DataFrame(
        {
            "competencia": [_format_competencia(row.get("competencia_dt"), row.get("competencia")) for _, row in df.iterrows()],
            "serie": "% Subordinação Total ex-360",
            "valor": pd.to_numeric(df.get("subordinacao_total_ex360_pct"), errors="coerce"),
        }
    )
    line_df["valor_fmt"] = line_df["valor"].map(_format_percent)
    line_label_df = _last_point_label_df(line_df, value_column="valor")
    x_sort = bar_df["competencia"].drop_duplicates().tolist()
    x = alt.X("competencia:N", title="Competência", sort=x_sort)
    bars = (
        alt.Chart(bar_df)
        .mark_bar()
        .encode(
            x=x,
            y=alt.Y(
                "valor_scaled:Q",
                title=scale_label,
                stack="zero",
                axis=alt.Axis(labelPadding=8, titlePadding=12, labelColor=CORES_MELI["auxiliar"], titleColor=CORES_MELI["auxiliar"]),
            ),
            color=alt.Color(
                "serie:N",
                title="PL",
                scale=alt.Scale(domain=["Sênior", "Subordinada + Mez ex-360"], range=[SENIOR_COLOR, SUB_MEZZ_COLOR]),
            ),
            order=alt.Order("ordem:Q"),
            tooltip=[
                alt.Tooltip("competencia:N", title="Competência"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor_fmt:N", title="Valor"),
            ],
        )
    )
    line = (
        alt.Chart(line_df)
        .mark_line(
            point=alt.OverlayMarkDef(filled=True, fill=SUBORDINATION_COLOR, color=SUBORDINATION_COLOR, size=42),
            strokeWidth=2,
            color=SUBORDINATION_COLOR,
        )
        .encode(
            x=x,
            y=alt.Y(
                "valor:Q",
                title="% Subordinação Total ex-360",
                scale=alt.Scale(zero=True, nice=True),
                axis=_percent_axis(orient="right", grid=False, color=SUBORDINATION_COLOR),
            ),
            tooltip=[
                alt.Tooltip("competencia:N", title="Competência"),
                alt.Tooltip("valor_fmt:N", title="% Subordinação Total ex-360"),
            ],
        )
    )
    line_label = _line_end_label(line_label_df, x=x, y_field="valor", text_field="valor_fmt", color=SUBORDINATION_COLOR, dy=-10)
    return _style_chart(alt.layer(bars, line + line_label).resolve_scale(y="independent").properties(height=360))


def npl_coverage_chart(monthly_df: pd.DataFrame, *, title: str = "NPL e Cobertura Ex-Vencidos > 360d") -> alt.Chart:
    if monthly_df.empty:
        return _empty_chart(title=title)
    df = monthly_df.sort_values("competencia_dt").copy()
    x_values = [_format_competencia(row.get("competencia_dt"), row.get("competencia")) for _, row in df.iterrows()]
    chart_df = pd.DataFrame(
        {
            "competencia": x_values,
            "npl_pct": pd.to_numeric(df.get("npl_over90_ex360_pct"), errors="coerce"),
            "coverage_pct": pd.to_numeric(df.get("pdd_npl_over90_ex360_pct"), errors="coerce"),
        }
    )
    chart_df["npl_fmt"] = chart_df["npl_pct"].map(_format_percent)
    chart_df["coverage_fmt"] = chart_df["coverage_pct"].map(_format_percent)
    npl_df = chart_df.assign(serie="NPL Over 90d ex-360 / Carteira")
    coverage_df = chart_df.assign(serie="PDD Ex / NPL Over 90d ex-360")
    npl_label_df = _last_point_label_df(chart_df[["competencia", "npl_pct", "npl_fmt"]], value_column="npl_pct")
    coverage_label_df = _last_point_label_df(chart_df[["competencia", "coverage_pct", "coverage_fmt"]], value_column="coverage_pct")
    x_sort = chart_df["competencia"].drop_duplicates().tolist()
    x = alt.X("competencia:N", title="Competência", sort=x_sort)
    color = alt.Color(
        "serie:N",
        title="Séries",
        scale=alt.Scale(
            domain=["NPL Over 90d ex-360 / Carteira", "PDD Ex / NPL Over 90d ex-360"],
            range=[NPL_COLOR, COVERAGE_COLOR],
        ),
        legend=alt.Legend(orient="bottom"),
    )
    npl_line = (
        alt.Chart(npl_df)
        .mark_line(
            point=alt.OverlayMarkDef(filled=True, size=42),
            strokeWidth=2,
        )
        .encode(
            x=x,
            y=alt.Y(
                "npl_pct:Q",
                title="NPL Over 90d Ex 360 / Carteira Ex 360",
                scale=alt.Scale(zero=True, nice=True),
                axis=_percent_axis(color=NPL_COLOR),
            ),
            color=color,
            tooltip=[alt.Tooltip("competencia:N", title="Competência"), alt.Tooltip("npl_fmt:N", title="NPL Over 90d Ex 360")],
        )
    )
    coverage_line = (
        alt.Chart(coverage_df)
        .mark_line(
            point=alt.OverlayMarkDef(filled=True, size=42),
            strokeWidth=2,
        )
        .encode(
            x=x,
            y=alt.Y(
                "coverage_pct:Q",
                title="PDD / NPL Over 90d Ex 360",
                scale=alt.Scale(zero=True, nice=True),
                axis=_percent_axis(orient="right", grid=False, color=COVERAGE_COLOR),
            ),
            color=color,
            tooltip=[alt.Tooltip("competencia:N", title="Competência"), alt.Tooltip("coverage_fmt:N", title="PDD / NPL Over 90d Ex 360")],
        )
    )
    npl_label = _line_end_label(npl_label_df, x=x, y_field="npl_pct", text_field="npl_fmt", color=NPL_COLOR, dy=-10)
    coverage_label = _line_end_label(coverage_label_df, x=x, y_field="coverage_pct", text_field="coverage_fmt", color=COVERAGE_COLOR, dy=14)
    return _style_chart(alt.layer(npl_line + npl_label, coverage_line + coverage_label).resolve_scale(y="independent").properties(height=340))


def _empty_chart(*, title: str) -> alt.Chart:
    return _style_chart(
        alt.Chart(pd.DataFrame({"x": [0], "text": ["Sem dados"]}))
        .mark_text(color="#6f7a87", fontSize=13)
        .encode(text="text:N")
        .properties(height=260)
    )


def _style_chart(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_axis(
            labelColor=CORES_MELI["auxiliar"],
            titleColor=CORES_MELI["auxiliar"],
            gridColor=CORES_MELI["cinza_claro"],
            domainColor=CORES_MELI["cinza_claro"],
        )
        .configure_view(stroke=None)
        .configure_legend(labelColor=CORES_MELI["auxiliar"], titleColor=CORES_MELI["auxiliar"], orient="bottom")
    )


def _percent_axis(*, color: str, orient: str | None = None, grid: bool = True) -> alt.Axis:
    kwargs: dict[str, object] = {
        "grid": grid,
        "tickCount": 6,
        "labelExpr": "replace(format(datum.value, '.1f'), '.', ',') + '%'",
        "labelColor": color,
        "titleColor": color,
        "labelPadding": 8,
        "titlePadding": 12,
    }
    if orient is not None:
        kwargs["orient"] = orient
    return alt.Axis(**kwargs)


def _last_point_label_df(df: pd.DataFrame, *, value_column: str) -> pd.DataFrame:
    if df.empty or value_column not in df.columns:
        return df.iloc[0:0].copy()
    last = df.tail(1).copy()
    value = pd.to_numeric(last[value_column], errors="coerce").iloc[0]
    if pd.isna(value):
        return df.iloc[0:0].copy()
    return last


def _line_end_label(
    label_df: pd.DataFrame,
    *,
    x: alt.X,
    y_field: str,
    text_field: str,
    color: str,
    dy: int,
) -> alt.Chart:
    return (
        alt.Chart(label_df)
        .mark_text(align="left", baseline="middle", dx=8, dy=dy, color=color, fontSize=11, fontWeight=600)
        .encode(
            x=x,
            y=alt.Y(f"{y_field}:Q", axis=None),
            text=alt.Text(f"{text_field}:N"),
        )
    )


def _money_scale(values: pd.Series) -> tuple[float, str]:
    max_value = pd.to_numeric(values, errors="coerce").abs().max()
    if pd.isna(max_value):
        max_value = 0.0
    if max_value >= 1_000_000_000_000:
        return 1_000_000_000.0, "R$ bi"
    if max_value >= 1_000_000:
        return 1_000_000.0, "R$ mm"
    if max_value >= 1_000:
        return 1_000.0, "R$ mil"
    return 1.0, "R$"


def _format_competencia(competencia_dt: object, fallback: object) -> str:
    ts = pd.to_datetime(competencia_dt, errors="coerce")
    if pd.notna(ts):
        return f"{PT_MONTH_ABBR[int(ts.month)]}/{str(int(ts.year))[-2:]}"
    return str(fallback or "")


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _divide(value: object, divisor: float) -> float | None:
    numeric = _num(value)
    if numeric is None:
        return None
    return numeric / divisor


def _format_decimal(value: object, decimals: int = 2) -> str:
    numeric = _num(value)
    if numeric is None:
        return "N/D"
    formatted = f"{numeric:,.{decimals}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_percent(value: object) -> str:
    return f"{_format_decimal(value, 1)}%"


def _format_money(value: object, *, scale_divisor: float, scale_label: str) -> str:
    numeric = _num(value)
    if numeric is None:
        return "N/D"
    value_divisor, value_label = _money_scale(pd.Series([numeric]))
    if value_label == "R$":
        return f"R$ {_format_decimal(numeric, 2)}"
    return f"{value_label} {_format_decimal(numeric / value_divisor, 1)}"
