from __future__ import annotations

import pandas as pd
import altair as alt

from services.mercado_livre_dashboard import PT_MONTH_ABBR
from services.mercado_livre_visuals import CORES_MELI


PRIMARY = CORES_MELI["primaria"]
SECONDARY = CORES_MELI["secundaria"]
AUX = CORES_MELI["auxiliar"]
GRID = CORES_MELI["cinza_claro"]
AXIS = "#000000"
STANDARD_CHART_HEIGHT = 360
SPLIT_PANEL_HEIGHT = 150
SPLIT_PANEL_SPACING = 8
COHORT_COLORS = ["#D9D9D9", "#BDBDBD", "#A0A0A0", "#838383", "#666666", "#4A4A4A", "#242424", "#000000"]


def roll_rates_chart(monitor_df: pd.DataFrame) -> alt.Chart:
    if monitor_df is None or monitor_df.empty:
        return _empty_chart()
    df = _chart_base(monitor_df)
    chart_df = pd.concat(
        [
            _line_series(df, "roll_61_90_m3_pct", "Roll 61-90 / carteira a vencer M-3"),
            _line_series(df, "roll_91_120_m4_pct", "Roll 91-120 / carteira a vencer M-4"),
            _line_series(df, "roll_121_150_m5_pct", "Roll 121-150 / carteira a vencer M-5"),
            _line_series(df, "roll_151_180_m6_pct", "Roll 151-180 / carteira a vencer M-6"),
        ],
        ignore_index=True,
    )
    color_domain = [
        "Roll 61-90 / carteira a vencer M-3",
        "Roll 91-120 / carteira a vencer M-4",
        "Roll 121-150 / carteira a vencer M-5",
        "Roll 151-180 / carteira a vencer M-6",
    ]
    return _line_chart(
        chart_df,
        y_title="Roll rate",
        color_domain=color_domain,
    )


def npl_severity_chart(monitor_df: pd.DataFrame) -> alt.Chart:
    if monitor_df is None or monitor_df.empty:
        return _empty_chart()
    df = _chart_base(monitor_df)
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        rows.append(
            {
                "competencia": row["competencia_label"],
                "serie": "NPL 1-90d",
                "valor": _num(row.get("npl_1_90_pct")),
                "valor_fmt": _format_percent(row.get("npl_1_90_pct")),
                "stack_order": 1,
            }
        )
        rows.append(
            {
                "competencia": row["competencia_label"],
                "serie": "NPL 91-360d",
                "valor": _num(row.get("npl_91_360_pct")),
                "valor_fmt": _format_percent(row.get("npl_91_360_pct")),
                "stack_order": 2,
            }
        )
    chart_df = pd.DataFrame(rows)
    x_sort = df["competencia_label"].tolist()
    bars = (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X("competencia:N", title="Competência", sort=x_sort, axis=_category_axis()),
            y=alt.Y("valor:Q", title="% da carteira ex-360", stack="zero", axis=_percent_axis()),
            color=alt.Color(
                "serie:N",
                title="NPL",
                scale=alt.Scale(domain=["NPL 1-90d", "NPL 91-360d"], range=[PRIMARY, SECONDARY]),
                legend=alt.Legend(orient="bottom"),
            ),
            order=alt.Order("stack_order:Q", sort="ascending"),
            tooltip=[
                alt.Tooltip("competencia:N", title="Competência"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor_fmt:N", title="Valor"),
            ],
        )
    )
    label_layers = _bar_label_layers(
        _stacked_bar_edge_labels(chart_df, x_sort=x_sort),
        x=alt.X("competencia:N", sort=x_sort, axis=_category_axis()),
    )
    return _style_chart(alt.layer(bars, *label_layers).properties(height=STANDARD_CHART_HEIGHT, padding={"left": 96, "right": 112}))


def portfolio_growth_chart(monitor_df: pd.DataFrame) -> alt.Chart:
    if monitor_df is None or monitor_df.empty:
        return _empty_chart()
    df = _chart_base(monitor_df)
    divisor, label = _money_scale(df["carteira_ex360"])
    df["carteira_scaled"] = pd.to_numeric(df["carteira_ex360"], errors="coerce") / divisor
    df["carteira_fmt"] = df["carteira_ex360"].map(lambda value: _format_money(value, divisor=divisor, label=label))
    df["carteira_label"] = df["carteira_ex360"].map(lambda value: _format_money_label(value, divisor=divisor, label=label))
    df["yoy_fmt"] = df["carteira_ex360_yoy_pct"].map(_format_percent)
    x_sort = df["competencia_label"].tolist()
    x = alt.X("competencia_label:N", title="Competência", sort=x_sort, axis=_category_axis())
    bars = (
        alt.Chart(df)
        .mark_bar(color=PRIMARY)
        .encode(
            x=x,
            y=alt.Y("carteira_scaled:Q", title=label, axis=_decimal_axis()),
            tooltip=[
                alt.Tooltip("competencia_label:N", title="Competência"),
                alt.Tooltip("carteira_fmt:N", title="Carteira ex-360"),
            ],
        )
    )
    bar_label_df = df[["competencia_label", "carteira_scaled", "carteira_label"]].copy()
    bar_label_df = bar_label_df[pd.to_numeric(bar_label_df["carteira_scaled"], errors="coerce").notna()]
    bar_label = (
        alt.Chart(bar_label_df)
        .mark_text(align="right", baseline="middle", dx=-8, dy=-8, color=PRIMARY, fontSize=11, fontWeight=600)
        .encode(
            x=alt.X("competencia_label:N", title="Competência", sort=x_sort),
            y=alt.Y("carteira_scaled:Q", title=label, axis=_decimal_axis()),
            text=alt.Text("carteira_label:N"),
        )
    )
    bar_chart = alt.layer(bars, bar_label).properties(
        width="container",
        height=SPLIT_PANEL_HEIGHT,
        title=_panel_title("Carteira ex-360"),
    )
    line = (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(filled=True, fill=SECONDARY, color=SECONDARY, size=42), color=SECONDARY, strokeWidth=2)
        .encode(
            x=x,
            y=alt.Y("carteira_ex360_yoy_pct:Q", title="Crescimento YoY", axis=_percent_axis(grid=True)),
            tooltip=[
                alt.Tooltip("competencia_label:N", title="Competência"),
                alt.Tooltip("yoy_fmt:N", title="Crescimento YoY"),
            ],
        )
    )
    line_label_df = _last_point_label_df(
        df[["competencia_label", "carteira_ex360_yoy_pct", "yoy_fmt"]],
        value_column="carteira_ex360_yoy_pct",
    )
    line_label = (
        alt.Chart(line_label_df)
        .mark_text(align="right", baseline="middle", dx=-8, dy=-12, color=SECONDARY, fontSize=11, fontWeight=600)
        .encode(
            x=alt.X("competencia_label:N", title="Competência", sort=x_sort),
            y=alt.Y("carteira_ex360_yoy_pct:Q", title="Crescimento YoY", axis=_percent_axis()),
            text=alt.Text("yoy_fmt:N"),
        )
    )
    yoy_chart = alt.layer(line, line_label).properties(
        width="container",
        height=SPLIT_PANEL_HEIGHT,
        title=_panel_title("Crescimento YoY"),
    )
    return _style_chart(
        alt.vconcat(
            bar_chart,
            yoy_chart,
            spacing=SPLIT_PANEL_SPACING,
            autosize=alt.AutoSizeParams(type="fit-x", contains="padding"),
        )
        .resolve_scale(x="shared")
    )


def duration_chart(consolidated_monitor: pd.DataFrame, fund_monitor: dict[str, pd.DataFrame]) -> alt.Chart:
    frames: list[pd.DataFrame] = []
    if consolidated_monitor is not None and not consolidated_monitor.empty:
        frames.append(_duration_series(consolidated_monitor, "Consolidado"))
    for _, frame in fund_monitor.items():
        if frame is None or frame.empty:
            continue
        name = str(frame["fund_name"].dropna().iloc[0]) if "fund_name" in frame.columns and frame["fund_name"].notna().any() else "FIDC"
        frames.append(_duration_series(frame, name))
    chart_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if chart_df.empty:
        return _empty_chart()
    x_sort = chart_df.drop_duplicates("competencia")["competencia"].tolist()
    color_domain = chart_df["serie"].drop_duplicates().tolist()
    color_range = _palette_for_domain(color_domain)
    x = alt.X("competencia:N", title="Competência", sort=x_sort, axis=_category_axis())
    line = (
        alt.Chart(chart_df)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=36), strokeWidth=2)
        .encode(
            x=x,
            y=alt.Y("duration_months:Q", title="Duration (meses)", scale=alt.Scale(zero=False, nice=True), axis=_decimal_axis()),
            color=alt.Color("serie:N", title="FIDC", scale=alt.Scale(domain=color_domain, range=color_range), legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("competencia:N", title="Competência"),
                alt.Tooltip("serie:N", title="FIDC"),
                alt.Tooltip("duration_fmt:N", title="Duration"),
            ],
        )
    )
    label_df = _assign_label_offsets(_last_point_labels(chart_df, value_column="duration_months"), value_column="duration_months")
    label_layers = _line_label_layers(
        label_df,
        x=x,
        y_field="duration_months",
        text_field="duration_fmt",
        color_map=dict(zip(color_domain, color_range, strict=False)),
    )
    return _style_chart(alt.layer(line, *label_layers).properties(height=STANDARD_CHART_HEIGHT))


def cohort_chart(cohort_df: pd.DataFrame, *, max_cohorts: int = 8) -> alt.Chart:
    if cohort_df is None or cohort_df.empty:
        return _empty_chart()
    df = cohort_df.copy()
    df["cohort_dt"] = pd.to_datetime(df["cohort_dt"], errors="coerce")
    recent = df[["cohort", "cohort_dt"]].drop_duplicates().sort_values("cohort_dt").tail(max_cohorts)["cohort"].tolist()
    df = df[df["cohort"].isin(recent)].copy()
    df["valor_fmt"] = df["valor_pct"].map(_format_percent)
    color_domain = recent
    color_range = _cohort_color_range(color_domain)
    x = alt.X("mes_ciclo:N", title="Mês de maturação", sort=["M1", "M2", "M3", "M4", "M5", "M6"], axis=_category_axis())
    y_scale = _tight_percent_scale(df["valor_pct"])
    line = (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=42), strokeWidth=2)
        .encode(
            x=x,
            y=alt.Y("valor_pct:Q", title="% do saldo a vencer em 30d", axis=_percent_axis(), scale=y_scale),
            color=alt.Color("cohort:N", title="Safra", scale=alt.Scale(domain=color_domain, range=color_range), legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("cohort:N", title="Safra"),
                alt.Tooltip("mes_ciclo:N", title="Mês"),
                alt.Tooltip("valor_fmt:N", title="Valor"),
            ],
        )
    )
    label_base = _last_point_labels(df.rename(columns={"cohort": "serie"}), value_column="valor_pct")
    label_df = _assign_label_offsets(label_base, value_column="valor_pct").rename(columns={"serie": "cohort"})
    label_layers = _line_label_layers(
        label_df,
        x=x,
        y_field="valor_pct",
        text_field="valor_fmt",
        color_map=dict(zip(color_domain, color_range, strict=False)),
        series_column="cohort",
    )
    return _style_chart(alt.layer(line, *label_layers).properties(height=STANDARD_CHART_HEIGHT))


def research_roll_seasonality_chart(roll_df: pd.DataFrame, *, metric_id: str) -> alt.Chart:
    if roll_df is None or roll_df.empty:
        return _empty_chart()
    df = roll_df[roll_df["metric_id"].eq(metric_id)].copy()
    if df.empty:
        return _empty_chart()
    df["month"] = pd.to_numeric(df.get("month"), errors="coerce")
    df["value_pct"] = pd.to_numeric(df.get("value_pct"), errors="coerce")
    df["series_name"] = df.get("series_name", pd.Series(dtype="object")).astype(str)
    df["valor_fmt"] = df["value_pct"].map(_format_percent)
    df = df.sort_values(["year", "month"]).reset_index(drop=True)
    month_domain = [PT_MONTH_ABBR[month].title() for month in range(1, 13)]
    series_domain = sorted(df["series_name"].dropna().unique().tolist())
    colors = _seasonality_colors(series_domain)
    x = alt.X("month_label:N", title="Mês do ano", sort=month_domain, axis=_category_axis())
    line = (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=42), strokeWidth=2)
        .encode(
            x=x,
            y=alt.Y("value_pct:Q", title="Roll rate", axis=_percent_axis(), scale=alt.Scale(zero=False, nice=True)),
            color=alt.Color("series_name:N", title="Ano", scale=alt.Scale(domain=series_domain, range=colors), legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("series_name:N", title="Ano"),
                alt.Tooltip("month_label:N", title="Mês"),
                alt.Tooltip("valor_fmt:N", title="Valor"),
                alt.Tooltip("formula:N", title="Fórmula"),
            ],
        )
    )
    label_base = _last_point_labels(df.rename(columns={"series_name": "serie"}), value_column="value_pct")
    label_df = _assign_label_offsets(label_base, value_column="value_pct")
    label_layers = _line_label_layers(
        label_df,
        x=x,
        y_field="value_pct",
        text_field="valor_fmt",
        color_map=dict(zip(series_domain, colors, strict=False)),
    )
    return _style_chart(alt.layer(line, *label_layers).properties(height=STANDARD_CHART_HEIGHT))


def research_cohort_chart(cohort_df: pd.DataFrame) -> alt.Chart:
    if cohort_df is None or cohort_df.empty:
        return _empty_chart()
    df = cohort_df.copy()
    df["value_pct"] = pd.to_numeric(df.get("value_pct"), errors="coerce")
    df["valor_fmt"] = df["value_pct"].map(_format_percent)
    df["series_name"] = df.get("series_name", pd.Series(dtype="object")).astype(str)
    df["ordem"] = pd.to_numeric(df.get("ordem"), errors="coerce")
    df = df.sort_values(["series_type", "line_rank", "ordem"]).reset_index(drop=True)
    series_domain = _cohort_research_domain(df)
    color_range = _research_cohort_colors(series_domain)
    dash_domain = series_domain
    dash_range = _research_cohort_dashes(df, series_domain)
    x = alt.X("mes_ciclo:N", title="Mês de maturação", sort=["M1", "M2", "M3", "M4", "M5", "M6"], axis=_category_axis())
    line = (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=38), strokeWidth=2)
        .encode(
            x=x,
            y=alt.Y("value_pct:Q", title="% do saldo a vencer em 30d", axis=_percent_axis(), scale=_tight_percent_scale(df["value_pct"])),
            color=alt.Color("series_name:N", title="Safra/média", scale=alt.Scale(domain=series_domain, range=color_range), legend=alt.Legend(orient="bottom")),
            strokeDash=alt.StrokeDash("series_name:N", title="Tipo", scale=alt.Scale(domain=dash_domain, range=dash_range), legend=None),
            tooltip=[
                alt.Tooltip("series_name:N", title="Linha"),
                alt.Tooltip("series_type:N", title="Tipo"),
                alt.Tooltip("mes_ciclo:N", title="Mês"),
                alt.Tooltip("valor_fmt:N", title="Valor"),
                alt.Tooltip("formula:N", title="Fórmula"),
            ],
        )
    )
    label_base = _last_point_labels(df.rename(columns={"series_name": "serie"}), value_column="value_pct")
    label_df = _assign_label_offsets(label_base, value_column="value_pct")
    label_layers = _line_label_layers(
        label_df,
        x=x,
        y_field="value_pct",
        text_field="valor_fmt",
        color_map=dict(zip(series_domain, color_range, strict=False)),
    )
    return _style_chart(alt.layer(line, *label_layers).properties(height=STANDARD_CHART_HEIGHT))


def _line_chart(chart_df: pd.DataFrame, *, y_title: str, color_domain: list[str]) -> alt.Chart:
    if chart_df.empty:
        return _empty_chart()
    x_sort = chart_df.drop_duplicates("competencia")["competencia"].tolist()
    color_range = _palette_for_domain(color_domain)
    x = alt.X("competencia:N", title="Competência", sort=x_sort, axis=_category_axis())
    line = (
        alt.Chart(chart_df)
        .mark_line(point=alt.OverlayMarkDef(filled=True, size=42), strokeWidth=2)
        .encode(
            x=x,
            y=alt.Y("valor:Q", title=y_title, axis=_percent_axis()),
            color=alt.Color(
                "serie:N",
                title="Séries",
                scale=alt.Scale(domain=color_domain, range=color_range),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("competencia:N", title="Competência"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor_fmt:N", title="Valor"),
            ],
        )
    )
    label_df = _assign_label_offsets(_last_point_labels(chart_df, value_column="valor"), value_column="valor")
    label_layers = _line_label_layers(
        label_df,
        x=x,
        y_field="valor",
        text_field="valor_fmt",
        color_map=dict(zip(color_domain, color_range, strict=False)),
    )
    return _style_chart(alt.layer(line, *label_layers).properties(height=STANDARD_CHART_HEIGHT))


def _line_series(df: pd.DataFrame, column: str, label: str) -> pd.DataFrame:
    if column not in df.columns:
        return pd.DataFrame(columns=["competencia", "serie", "valor", "valor_fmt"])
    out = pd.DataFrame(
        {
            "competencia": df["competencia_label"],
            "serie": label,
            "valor": pd.to_numeric(df[column], errors="coerce"),
        }
    )
    out["valor_fmt"] = out["valor"].map(_format_percent)
    return out


def _duration_series(df: pd.DataFrame, label: str) -> pd.DataFrame:
    base = _chart_base(df)
    out = pd.DataFrame(
        {
            "competencia": base["competencia_label"],
            "serie": label,
            "duration_months": pd.to_numeric(base.get("duration_months"), errors="coerce"),
        }
    )
    out["duration_fmt"] = out["duration_months"].map(lambda value: f"{_format_decimal(value, 1)} meses")
    return out


def _last_point_label_df(df: pd.DataFrame, *, value_column: str) -> pd.DataFrame:
    if df.empty or value_column not in df.columns:
        return df.iloc[0:0].copy()
    valid = df[pd.to_numeric(df[value_column], errors="coerce").notna()]
    return valid.tail(1).copy() if not valid.empty else df.iloc[0:0].copy()


def _last_point_labels(df: pd.DataFrame, *, value_column: str, series_column: str = "serie") -> pd.DataFrame:
    if df.empty or value_column not in df.columns or series_column not in df.columns:
        return df.iloc[0:0].copy()
    rows = []
    for _, group in df.groupby(series_column, sort=False):
        valid = group[pd.to_numeric(group[value_column], errors="coerce").notna()]
        if not valid.empty:
            rows.append(valid.tail(1))
    return pd.concat(rows, ignore_index=True, sort=False) if rows else df.iloc[0:0].copy()


def _assign_label_offsets(df: pd.DataFrame, *, value_column: str) -> pd.DataFrame:
    output = df.copy()
    if output.empty:
        output["label_dy"] = pd.Series(dtype="int")
        return output
    values = pd.to_numeric(output[value_column], errors="coerce")
    if values.notna().sum() <= 1:
        output["label_dy"] = -12
        return output
    value_range = float(values.max() - values.min())
    threshold = max(value_range * 0.08, 0.5)
    offsets = [-12, 14, -26, 28, -40, 42, -54, 56]
    output["label_dy"] = -12
    used: list[float] = []
    for idx, value in values.sort_values(ascending=False).items():
        if pd.isna(value):
            continue
        close_count = sum(abs(float(value) - prior) <= threshold for prior in used)
        output.loc[idx, "label_dy"] = offsets[min(close_count, len(offsets) - 1)]
        used.append(float(value))
    return output


def _line_label_layers(
    label_df: pd.DataFrame,
    *,
    x: alt.X,
    y_field: str,
    text_field: str,
    color_map: dict[str, str],
    series_column: str = "serie",
) -> list[alt.Chart]:
    layers: list[alt.Chart] = []
    if label_df.empty or series_column not in label_df.columns:
        return layers
    for _, row in label_df.iterrows():
        series = str(row.get(series_column) or "")
        dy = int(row.get("label_dy") or -12)
        layers.append(
            alt.Chart(pd.DataFrame([row]))
            .mark_text(
                align="left",
                baseline="middle",
                dx=8,
                dy=dy,
                color=color_map.get(series, AUX),
                fontSize=11,
                fontWeight=600,
            )
            .encode(
                x=x,
                y=alt.Y(f"{y_field}:Q"),
                text=alt.Text(f"{text_field}:N"),
            )
        )
    return layers


def _stacked_bar_edge_labels(chart_df: pd.DataFrame, *, x_sort: list[str]) -> pd.DataFrame:
    if chart_df.empty or not x_sort:
        return pd.DataFrame(columns=["competencia", "serie", "label_y", "label_text", "label_color", "label_dx", "label_dy", "label_align"])
    rows: list[dict[str, object]] = []
    edge_competencias = [x_sort[0]]
    if x_sort[-1] != x_sort[0]:
        edge_competencias.append(x_sort[-1])
    series_order = [("NPL 1-90d", PRIMARY), ("NPL 91-360d", SECONDARY)]
    for edge_index, competencia in enumerate(edge_competencias):
        align = "right" if edge_index == 0 else "left"
        dx = -12 if edge_index == 0 else 12
        final = chart_df[chart_df["competencia"].eq(competencia)].copy()
        if final.empty:
            continue
        cumulative = 0.0
        total = 0.0
        for serie, color in series_order:
            row = final[final["serie"].eq(serie)]
            if row.empty:
                continue
            value = _num(row.iloc[0].get("valor"))
            if value is None or value <= 0:
                continue
            rows.append(
                {
                    "competencia": competencia,
                    "serie": serie,
                    "label_y": cumulative + value / 2.0,
                    "label_text": row.iloc[0].get("valor_fmt"),
                    "label_color": color,
                    "label_dx": dx,
                    "label_dy": 0,
                    "label_align": align,
                }
            )
            cumulative += value
            total += value
        if total > 0:
            rows.append(
                {
                    "competencia": competencia,
                    "serie": "Total",
                    "label_y": total,
                    "label_text": f"Total {_format_percent(total)}",
                    "label_color": AUX,
                    "label_dx": 0,
                    "label_dy": -12,
                    "label_align": "center",
                }
            )
    return pd.DataFrame(rows)


def _bar_label_layers(label_df: pd.DataFrame, *, x: alt.X) -> list[alt.Chart]:
    layers: list[alt.Chart] = []
    if label_df.empty:
        return layers
    for _, row in label_df.iterrows():
        layers.append(
            alt.Chart(pd.DataFrame([row]))
            .mark_text(
                align=str(row.get("label_align") or "left"),
                baseline="middle",
                color=str(row.get("label_color") or "#000000"),
                clip=False,
                dx=int(row.get("label_dx") or 0),
                dy=int(row.get("label_dy") or 0),
                fontSize=10,
                fontWeight=700,
            )
            .encode(
                x=x,
                y=alt.Y("label_y:Q", title="% da carteira ex-360", axis=_percent_axis()),
                text=alt.Text("label_text:N"),
            )
        )
    return layers


def _palette_for_domain(domain: list[str]) -> list[str]:
    base = [PRIMARY, SECONDARY, AUX, "#8C8C8C"]
    return [base[idx % len(base)] for idx, _ in enumerate(domain or base)]


def _seasonality_colors(domain: list[str]) -> list[str]:
    if not domain:
        return [PRIMARY]
    base = ["#BDBDBD", AUX, SECONDARY, PRIMARY]
    if len(domain) <= len(base):
        return base[-len(domain):]
    extra = ["#D9D9D9"] * (len(domain) - len(base))
    return extra + base


def _cohort_color_range(domain: list[str]) -> list[str]:
    if not domain:
        return COHORT_COLORS
    count = len(domain)
    return COHORT_COLORS[-count:]


def _cohort_research_domain(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    benchmarks = df[df["series_type"].astype(str).str.contains("Média", na=False)]["series_name"].drop_duplicates().tolist()
    recent = df[~df["series_name"].isin(benchmarks)][["series_name", "line_rank"]].drop_duplicates()
    recent = recent.sort_values("line_rank")["series_name"].tolist()
    return benchmarks + recent


def _research_cohort_colors(domain: list[str]) -> list[str]:
    if not domain:
        return [PRIMARY]
    grays = ["#D9D9D9", "#C6C6C6", "#AFAFAF", "#989898", "#818181", "#696969", "#4F4F4F", "#303030", "#000000"]
    if len(domain) <= len(grays):
        return grays[-len(domain):]
    return ["#E5E5E5"] * (len(domain) - len(grays)) + grays


def _research_cohort_dashes(df: pd.DataFrame, domain: list[str]) -> list[list[int]]:
    if not domain:
        return [[]]
    latest_recent = None
    recent = df[~df["series_type"].astype(str).str.contains("Média", na=False)][["series_name", "line_rank"]].drop_duplicates()
    if not recent.empty:
        latest_recent = str(recent.sort_values("line_rank")["series_name"].iloc[-1])
    patterns = [[6, 4], [3, 3], [1, 3], [8, 3], [2, 2], [4, 2]]
    out: list[list[int]] = []
    for idx, series in enumerate(domain):
        if series == latest_recent:
            out.append([])
        else:
            out.append(patterns[idx % len(patterns)])
    return out


def _chart_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["competencia_dt"] = pd.to_datetime(out["competencia_dt"], errors="coerce")
    out = out.sort_values("competencia_dt").reset_index(drop=True)
    out["competencia_label"] = [
        _format_competencia(row.get("competencia_dt"), row.get("competencia"))
        for _, row in out.iterrows()
    ]
    return out


def _style_chart(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_axis(
            labelColor=AUX,
            titleColor=AUX,
            gridColor=GRID,
            domain=True,
            ticks=True,
            labels=True,
            domainColor=AXIS,
            tickColor=AXIS,
            labelFontSize=11,
            titleFontSize=12,
        )
        .configure_view(stroke=None)
        .configure_legend(labelColor=AUX, titleColor=AUX, orient="bottom", labelFontSize=11, titleFontSize=11)
    )


def _panel_title(text: str) -> alt.TitleParams:
    return alt.TitleParams(
        text=text,
        anchor="start",
        color=AXIS,
        fontSize=13,
        fontWeight=600,
        offset=6,
    )


def _percent_axis(*, orient: str | None = None, grid: bool = True) -> alt.Axis:
    kwargs: dict[str, object] = {
        "grid": grid,
        "domain": True,
        "ticks": True,
        "labels": True,
        "domainColor": AXIS,
        "tickColor": AXIS,
        "tickCount": 6,
        "labelExpr": "replace(format(datum.value, '.1f'), '.', ',') + '%'",
        "labelPadding": 8,
        "titlePadding": 12,
    }
    if orient is not None:
        kwargs["orient"] = orient
    return alt.Axis(**kwargs)


def _category_axis() -> alt.Axis:
    return alt.Axis(
        domain=True,
        ticks=True,
        labels=True,
        domainColor=AXIS,
        tickColor=AXIS,
        labelPadding=8,
        titlePadding=12,
        labelAngle=0,
    )


def _decimal_axis(*, grid: bool = True, orient: str | None = None) -> alt.Axis:
    kwargs: dict[str, object] = {
        "grid": grid,
        "domain": True,
        "ticks": True,
        "labels": True,
        "domainColor": AXIS,
        "tickColor": AXIS,
        "tickCount": 6,
        "labelExpr": "replace(format(datum.value, ',.1f'), '.', ',')",
        "labelPadding": 8,
        "titlePadding": 12,
    }
    if orient is not None:
        kwargs["orient"] = orient
    return alt.Axis(**kwargs)


def _tight_percent_scale(values: pd.Series) -> alt.Scale:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return alt.Scale(zero=False, nice=False)
    min_value = float(numeric.min())
    max_value = float(numeric.max())
    value_range = max_value - min_value
    if value_range <= 0:
        pad = max(abs(min_value) * 0.03, 0.25)
    else:
        pad = max(value_range * 0.08, 0.10)
    lower = min_value - pad
    upper = max_value + pad
    if min_value >= 0:
        lower = max(0.0, lower)
    return alt.Scale(domain=[lower, upper], zero=False, nice=False)


def _empty_chart() -> alt.Chart:
    return _style_chart(
        alt.Chart(pd.DataFrame({"x": [0], "text": ["Sem dados"]}))
        .mark_text(color="#6f7a87", fontSize=13)
        .encode(text="text:N")
        .properties(height=STANDARD_CHART_HEIGHT)
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


def _format_decimal(value: object, decimals: int = 1) -> str:
    numeric = _num(value)
    if numeric is None:
        return "N/D"
    return f"{numeric:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _format_percent(value: object) -> str:
    return f"{_format_decimal(value, 1)}%"


def _format_money(value: object, *, divisor: float, label: str) -> str:
    numeric = _num(value)
    if numeric is None:
        return "N/D"
    if label == "R$":
        return f"R$ {_format_decimal(numeric, 2)}"
    suffix = label.removeprefix("R$ ").strip()
    return f"R${_format_decimal(numeric / divisor, 0)}{suffix}"


def _format_money_label(value: object, *, divisor: float, label: str) -> str:
    numeric = _num(value)
    if numeric is None:
        return ""
    if label == "R$":
        return _format_decimal(numeric, 0)
    return _format_decimal(numeric / divisor, 0)
