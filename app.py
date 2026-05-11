from __future__ import annotations

import streamlit as st

from tabs.tab_fidc_book import render_tab_fidc_book
from tabs import tab_fidc_ime as ime_tab
from tabs.tab_fidc_monitoring import render_tab_fidc_monitoring
from tabs.tab_mercado_livre import render_tab_somatorio_fidcs
from tabs.tab_fidc_ime_carteira import render_tab_fidc_ime_carteira
from tabs.tab_modelo_fidc import render_tab_modelo_fidc


_APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

html, body, .stApp, .stMarkdown, .stDataFrame, .stTextInput, .stSelectbox, .stRadio, .stTabs, div, p, label, input, button, h1, h2, h3, h4, h5, h6, li, table, th, td {
    font-family: 'IBM Plex Sans', sans-serif !important;
}

.stApp {
    background: #ffffff;
    color: #2f3a48;
}

.block-container {
    padding-top: 1.25rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}

.fidc-app-header {
    margin: 0 0 1.1rem 0;
    max-width: 64rem;
}

.fidc-app-kicker {
    color: #1f77b4;
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    line-height: 1.2;
    margin-bottom: 0.3rem;
    text-transform: uppercase;
}

.fidc-app-title {
    color: #283241;
    font-size: 2.45rem;
    font-weight: 700;
    letter-spacing: 0;
    line-height: 1.08;
    margin: 0;
}

.fidc-app-subtitle {
    color: #6f7a87;
    font-size: 0.98rem;
    line-height: 1.55;
    margin-top: 0.65rem;
    max-width: 48rem;
}

.fidc-control-kicker {
    color: #ff5a00;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    line-height: 1.2;
    margin: 0.7rem 0 0.3rem 0;
    text-transform: uppercase;
}

[data-testid="stTabs"] [role="tablist"] {
    border-bottom: 1px solid #dde3ea;
    gap: 2rem;
    overflow-x: auto;
    scrollbar-width: thin;
}

/* Radio buttons → compact chips (period selector & portfolio view toggle) */
[data-testid="stRadio"] [role="radiogroup"],
[data-testid="stRadio"] [data-baseweb="radio-group"] {
    display: flex !important;
    gap: 0.45rem !important;
    flex-wrap: wrap;
    align-items: center;
}

[data-testid="stRadio"] [role="radiogroup"] > label,
[data-testid="stRadio"] [data-baseweb="radio-group"] > label {
    display: inline-flex !important;
    align-items: center !important;
    padding: 0.2rem 0.9rem !important;
    border-radius: 999px !important;
    border: 1.5px solid #dde3ea !important;
    background: #f7f8fa !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: #5a6478 !important;
    cursor: pointer !important;
    transition: background 0.12s, border-color 0.12s, color 0.12s !important;
    margin: 0 !important;
    line-height: 1.6 !important;
    white-space: nowrap !important;
}

/* Hide the radio circle SVG — show only the text */
[data-testid="stRadio"] [role="radiogroup"] > label > div:first-child,
[data-testid="stRadio"] [data-baseweb="radio-group"] > label > div:first-child {
    display: none !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label:hover,
[data-testid="stRadio"] [data-baseweb="radio-group"] > label:hover {
    border-color: #1f77b4 !important;
    color: #1f77b4 !important;
    background: #f0f4f8 !important;
}

/* Selected chip */
[data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked),
[data-testid="stRadio"] [data-baseweb="radio-group"] > label:has(input:checked) {
    background: #1f77b4 !important;
    border-color: #1f77b4 !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) *,
[data-testid="stRadio"] [data-baseweb="radio-group"] > label:has(input:checked) * {
    color: #ffffff !important;
}

.fidc-main-nav-marker {
    display: none;
}

div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [role="radiogroup"],
div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [data-baseweb="radio-group"] {
    border-bottom: 1px solid #dde3ea;
    display: flex !important;
    flex-wrap: nowrap !important;
    gap: 0 !important;
    overflow-x: auto !important;
    padding-bottom: 0 !important;
    scrollbar-width: thin;
}

div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [role="radiogroup"] > label,
div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [data-baseweb="radio-group"] > label {
    background: #ffffff !important;
    border: 0 !important;
    border-bottom: 2px solid transparent !important;
    border-radius: 0 !important;
    color: #2f3a48 !important;
    font-size: 0.95rem !important;
    font-weight: 500 !important;
    line-height: 2.4rem !important;
    padding: 0 1.05rem !important;
    white-space: nowrap !important;
}

div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [role="radiogroup"] > label:hover,
div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [data-baseweb="radio-group"] > label:hover {
    background: #ffffff !important;
    border-bottom-color: #8db7dc !important;
    color: #1f77b4 !important;
}

div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked),
div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [data-baseweb="radio-group"] > label:has(input:checked) {
    background: #ffffff !important;
    border-bottom-color: #1f77b4 !important;
    color: #1f77b4 !important;
    font-weight: 600 !important;
}

div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) *,
div.element-container:has(.fidc-main-nav-marker) + div.element-container [data-testid="stRadio"] [data-baseweb="radio-group"] > label:has(input:checked) * {
    color: #1f77b4 !important;
}

[data-testid="stTabs"] [role="tab"] {
    min-height: 2.55rem;
    white-space: nowrap;
}

[data-testid="stTabs"] [role="tab"] p {
    color: #2f3a48;
    font-size: 0.95rem;
}

[data-testid="stTabs"] [aria-selected="true"] p {
    color: #1f77b4;
    font-weight: 600;
}

[data-testid="stForm"] {
    border: 1px solid #dde3ea;
    border-radius: 8px;
    padding: 1rem 1rem 0.85rem 1rem;
}

[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] > div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] > div[data-baseweb="select"] > div {
    border-color: #dde3ea;
    border-radius: 8px;
}

@media (max-width: 760px) {
    .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    .fidc-app-title {
        font-size: 2rem;
    }

    .fidc-app-subtitle {
        font-size: 0.94rem;
    }
}
</style>
"""


st.set_page_config(page_title="tomaconta FIDCs", page_icon="📊", layout="wide")

st.markdown(_APP_CSS, unsafe_allow_html=True)
st.markdown(
    """
    <div class="fidc-app-header">
      <h1 class="fidc-app-title">tomaconta FIDCs</h1>
    </div>
    """,
    unsafe_allow_html=True,
)

# Global period selector — shared across Informe Mensal tabs to keep single-fund and portfolio views in sync.
_render_period_selector = getattr(ime_tab, "render_period_selector", None) or getattr(ime_tab, "_render_period_selector")
period = _render_period_selector(state_prefix="ime_global")


_MAIN_SECTIONS = [
    "Sobre",
    "Glossário FIDCs",
    "Informe Mensal Estruturado",
    "Acompanhamento Carteira",
    "Soma de FIDCs",
    "Monitoramento FIDCs",
    "Modelagem",
]

st.markdown("<div class='fidc-main-nav-marker'></div>", unsafe_allow_html=True)
selected_section = st.radio(
    "Seção",
    options=_MAIN_SECTIONS,
    key="fidc_main_section",
    horizontal=True,
    label_visibility="collapsed",
)

if selected_section == "Informe Mensal Estruturado":
    ime_tab.render_tab_fidc_ime(period=period)
elif selected_section == "Acompanhamento Carteira":
    render_tab_fidc_ime_carteira(period=period)
elif selected_section == "Soma de FIDCs":
    render_tab_somatorio_fidcs(period=period)
elif selected_section == "Monitoramento FIDCs":
    render_tab_fidc_monitoring(period=period)
elif selected_section == "Modelagem":
    render_tab_modelo_fidc()
elif selected_section == "Glossário FIDCs":
    render_tab_fidc_book()
elif selected_section == "Sobre":
    try:
        from tabs.tab_about import render_tab_about

        render_tab_about()
    except ModuleNotFoundError as exc:
        st.error("A tela Sobre ainda não foi carregada corretamente neste deploy.")
        st.caption(f"Módulo ausente: {exc.name}. As demais abas continuam disponíveis.")
    except Exception as exc:  # noqa: BLE001
        st.error("A tela Sobre encontrou um erro, mas as demais abas continuam disponíveis.")
        st.caption(f"Detalhe técnico: {type(exc).__name__}: {exc}")
