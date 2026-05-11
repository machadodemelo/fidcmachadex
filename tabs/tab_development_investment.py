from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from services.dev_hours import (
    CACHE_TTL_HOURS,
    DevHoursError,
    get_development_investment,
    invalidate_dev_hours_cache,
    load_cached_development_investment,
    load_dev_hours_config,
    read_github_token,
    save_dev_hours_config,
)


_DEV_HOURS_CSS = """
<style>
.dev-hours-section,
.dev-hours-section * {
    font-family: 'IBM Plex Sans', sans-serif !important;
}

.dev-hours-section {
    margin-top: 2.2rem;
    padding-top: 1.4rem;
    border-top: 1px solid #ece5de;
}

.dev-hours-title {
    color: #12171d;
    font-size: 1.65rem;
    line-height: 1.1;
    font-weight: 600;
    margin: 0 0 0.35rem 0;
}

.dev-hours-caption {
    color: #66717d;
    font-size: 0.92rem;
    line-height: 1.5;
    margin-bottom: 1rem;
    max-width: 58rem;
}

.dev-hours-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 0.9rem 0 0.9rem 0;
}

.dev-hours-card {
    background: #f7f8fa;
    border: 1px solid #e6ebf1;
    border-radius: 8px;
    padding: 0.78rem 0.85rem;
    min-height: 4.5rem;
}

.dev-hours-label {
    color: #68727d;
    font-size: 0.74rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    line-height: 1.25;
    text-transform: uppercase;
}

.dev-hours-value {
    color: #12171d;
    font-size: 1.28rem;
    font-weight: 700;
    line-height: 1.25;
    margin-top: 0.35rem;
}

.dev-hours-meta {
    color: #68727d;
    font-size: 0.84rem;
    line-height: 1.45;
    margin: 0.35rem 0 0.75rem 0;
}

.dev-hours-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin: 0.45rem 0 1rem 0;
}

.dev-hours-pill {
    color: #1f77b4;
    background: #f0f4f8;
    border: 1px solid #d9e4ef;
    border-radius: 999px;
    display: inline-flex;
    font-size: 0.82rem;
    font-weight: 600;
    line-height: 1.2;
    padding: 0.32rem 0.62rem;
}

@media (max-width: 980px) {
    .dev-hours-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 620px) {
    .dev-hours-grid {
        grid-template-columns: 1fr;
    }
}
</style>
"""


def render_development_investment_section() -> None:
    st.markdown(_DEV_HOURS_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="dev-hours-section">
          <div class="dev-hours-title">Investimento de Desenvolvimento</div>
          <div class="dev-hours-caption">
            Estimativa baseada em commits do GitHub: sessões de trabalho + Overhead de Sessão por sessão.
            Total = horas entre commits + overhead.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    config = load_dev_hours_config()
    _render_parameters(config)

    refresh_requested = st.button("Recalcular estimativa", key="dev_hours_recalculate", type="secondary")
    payload: dict[str, Any] | None
    warnings: list[str] = []
    if refresh_requested:
        token = read_github_token(secrets_mapping=_secrets_to_dict())
        try:
            with st.spinner("Calculando investimento de desenvolvimento pelo histórico do GitHub..."):
                payload, source, warnings = get_development_investment(config, token=token, refresh=True)
        except DevHoursError as exc:
            st.error(f"Não foi possível calcular a estimativa: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            st.error(f"Não foi possível calcular a estimativa neste momento: {exc}")
            return
    else:
        payload, source = load_cached_development_investment(config, allow_stale=True)
        if payload is None:
            _render_repo_pills(config.get("repositorios") or [])
            st.info("Clique em Recalcular estimativa para criar o primeiro cache local desta seção.")
            return

    _render_repo_pills(payload.get("repositorios") or config.get("repositorios") or [])
    _render_cache_meta(payload, source=source)
    for warning in [*(warnings or []), *(payload.get("warnings") or [])]:
        st.warning(str(warning))
    _render_cards(payload)
    _render_methodology(config, payload)
    _render_weekly_chart(payload)


def _render_parameters(config: dict[str, Any]) -> None:
    with st.expander("Parâmetros de estimativa", expanded=False):
        st.caption("A alteração dos parâmetros invalida o cache local e recalcula a seção na próxima execução.")
        with st.form("dev_hours_config_form"):
            limiar = st.number_input(
                "Limiar de sessão (min)",
                min_value=15,
                max_value=480,
                step=15,
                value=int(config.get("limiar_sessao_min") or 90),
                help="Gap máximo entre commits para continuar na mesma sessão de trabalho.",
            )
            overhead = st.number_input(
                "Overhead de Sessão (min)",
                min_value=0,
                max_value=240,
                step=5,
                value=int(config.get("overhead_sessao_min") or 20),
                help="Tempo fixo adicionado por sessão para planejamento, revisão, testes e contexto fora dos commits.",
            )
            repos_text = st.text_area(
                "Repositórios GitHub",
                value="\n".join(config.get("repositorios") or []),
                help="Use um repositório por linha no formato owner/repo.",
            )
            incluir_merges = st.checkbox("Incluir merge commits", value=bool(config.get("incluir_merges")))
            incluir_prs = st.checkbox("Incluir PRs como contexto", value=bool(config.get("incluir_prs", True)))
            submitted = st.form_submit_button("Salvar parâmetros")
        if submitted:
            save_dev_hours_config(
                {
                    "repositorios": repos_text,
                    "limiar_sessao_min": int(limiar),
                    "overhead_sessao_min": int(overhead),
                    "incluir_merges": bool(incluir_merges),
                    "incluir_prs": bool(incluir_prs),
                }
            )
            invalidate_dev_hours_cache()
            st.success("Parâmetros salvos. Cache invalidado.")
            st.rerun()


def _render_repo_pills(repositories: list[str]) -> None:
    pills = "".join(f"<span class='dev-hours-pill'>{escape(str(repo))}</span>" for repo in repositories)
    st.markdown(f"<div class='dev-hours-pills'>{pills}</div>", unsafe_allow_html=True)


def _render_cache_meta(payload: dict[str, Any], *, source: str) -> None:
    generated_at = _parse_dt(payload.get("generated_at"))
    generated_label = _format_datetime(generated_at) if generated_at else "não informado"
    source_label = {
        "cache": "cache válido",
        "cache_stale": "cache antigo preservado",
        "github": "GitHub",
    }.get(source, source)
    st.markdown(
        (
            "<div class='dev-hours-meta'>"
            f"Última atualização: <strong>{escape(generated_label)}</strong> · "
            f"TTL: <strong>{CACHE_TTL_HOURS}h</strong> · "
            f"Fonte exibida: <strong>{escape(source_label)}</strong>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_cards(payload: dict[str, Any]) -> None:
    cards = [
        ("Horas entre commits", _fmt_hours(payload.get("horas_base_commits"))),
        ("Overhead de Sessão", _fmt_hours(payload.get("horas_overhead"))),
        ("Total estimado", _fmt_hours(payload.get("total_horas"))),
        ("Sessões de trabalho", _fmt_int(payload.get("sessoes_trabalho"))),
        ("Sessão média", _fmt_hours(payload.get("sessao_media_horas"))),
        ("Commits considerados", _fmt_int(payload.get("total_commits"))),
        ("PRs mergeados", _fmt_int(payload.get("prs_mergeados"))),
    ]
    html = ["<div class='dev-hours-grid'>"]
    for label, value in cards:
        html.append(
            "<div class='dev-hours-card'>"
            f"<div class='dev-hours-label'>{escape(label)}</div>"
            f"<div class='dev-hours-value'>{escape(value)}</div>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _render_methodology(config: dict[str, Any], payload: dict[str, Any]) -> None:
    with st.expander("Como calculamos?", expanded=False):
        st.markdown(
            f"""
**Unidade principal:** commits. Cada commit tem data, mensagem, SHA e repositório.

**Deduplicação:** primeiro removemos commits com o mesmo SHA. Depois removemos possíveis duplicidades de repositórios espelhados usando a combinação `(timestamp em segundos, mensagem normalizada)`.

**Sessões de trabalho:** commits são ordenados por data. Uma nova sessão começa quando o intervalo entre dois commits passa de `{int(config.get("limiar_sessao_min") or 90)} minutos`.

**Horas entre commits:** para cada sessão, calculamos `último commit - primeiro commit`. Sessões com apenas um commit têm zero hora-base, mas ainda recebem overhead.

**Overhead de Sessão:** adicionamos `{int(config.get("overhead_sessao_min") or 20)} minutos por sessão para cobrir planejamento, leitura de contexto, testes, revisão e pequenas atividades que não aparecem diretamente no intervalo entre commits.

**Total estimado:** `horas entre commits + overhead`.

**Faixa estimada:** mínimo = horas entre commits; central = total estimado; máximo = horas entre commits + 1h por sessão.

**Pull requests:** entram como evidência complementar de atividade. PRs não somam horas para evitar dupla contagem, porque os commits do PR já estão na metodologia principal.
            """
        )
        st.caption(
            "Faixa estimada: "
            f"{_fmt_hours(payload.get('estimativa_min_horas'))} a "
            f"{_fmt_hours(payload.get('estimativa_max_horas'))}; "
            f"ponto central {_fmt_hours(payload.get('estimativa_central_horas'))}."
        )


def _render_weekly_chart(payload: dict[str, Any]) -> None:
    weekly = payload.get("weekly_breakdown") or []
    if not weekly:
        st.info("Sem sessões suficientes para montar o gráfico semanal.")
        return
    df = pd.DataFrame(weekly)
    if df.empty:
        return
    df["semana_inicio"] = pd.to_datetime(df["semana_inicio"], errors="coerce")
    chart_df = df.melt(
        id_vars=["semana_inicio"],
        value_vars=["horas_base_commits", "horas_overhead"],
        var_name="tipo",
        value_name="horas",
    )
    chart_df["tipo"] = chart_df["tipo"].map(
        {
            "horas_base_commits": "Horas entre commits",
            "horas_overhead": "Overhead de Sessão",
        }
    )
    chart = (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X("semana_inicio:T", title="Semana", axis=alt.Axis(format="%d/%m/%y")),
            y=alt.Y("horas:Q", title="Horas"),
            color=alt.Color(
                "tipo:N",
                title="Componente",
                scale=alt.Scale(domain=["Horas entre commits", "Overhead de Sessão"], range=["#1f77b4", "#ff5a00"]),
            ),
            tooltip=[
                alt.Tooltip("semana_inicio:T", title="Semana", format="%d/%m/%Y"),
                alt.Tooltip("tipo:N", title="Componente"),
                alt.Tooltip("horas:Q", title="Horas", format=".1f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, use_container_width=True)


def _secrets_to_dict() -> dict[str, Any]:
    try:
        return dict(st.secrets)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return {}


def _fmt_hours(value: Any) -> str:
    return f"{_fmt_float(_to_float(value), decimals=1)} h"


def _fmt_int(value: Any) -> str:
    numeric = _to_float(value)
    return _format_br_int(int(numeric or 0))


def _fmt_float(value: float | None, *, decimals: int) -> str:
    numeric = float(value or 0.0)
    return f"{numeric:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _format_br_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return numeric


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "não informado"
    return value.astimezone().strftime("%d/%m/%Y %H:%M")
