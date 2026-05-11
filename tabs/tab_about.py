from __future__ import annotations

import streamlit as st

from tabs.tab_development_investment import render_development_investment_section


_ABOUT_CSS = """
<style>
.about-page,
.about-page * {
    font-family: 'IBM Plex Sans', sans-serif !important;
}

.about-page {
    margin: 0.15rem 0 1.3rem 0;
    padding-bottom: 1rem;
    border-bottom: 1px solid #ece5de;
}

.about-kicker {
    color: #1f77b4;
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    line-height: 1.2;
    margin-bottom: 0.35rem;
    text-transform: uppercase;
}

.about-title {
    color: #12171d;
    font-size: 2.15rem;
    line-height: 1.08;
    font-weight: 650;
    margin: 0;
}

.about-summary {
    color: #59626d;
    font-size: 1rem;
    line-height: 1.62;
    margin-top: 0.65rem;
    max-width: 54rem;
}

.about-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
    margin: 1rem 0 0.4rem 0;
}

.about-card {
    background: #f7f8fa;
    border: 1px solid #e6ebf1;
    border-radius: 8px;
    padding: 0.9rem 1rem;
}

.about-card-title {
    color: #12171d;
    font-size: 0.96rem;
    font-weight: 650;
    margin-bottom: 0.35rem;
}

.about-card-body {
    color: #68727d;
    font-size: 0.9rem;
    line-height: 1.5;
}

@media (max-width: 900px) {
    .about-grid {
        grid-template-columns: 1fr;
    }
}
</style>
"""


def render_tab_about() -> None:
    st.markdown(_ABOUT_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="about-page">
          <div class="about-kicker">Sobre</div>
          <h2 class="about-title">tomaconta FIDCs</h2>
          <div class="about-summary">
            Aplicação para leitura, acompanhamento e análise de Informes Mensais Estruturados de FIDCs.
            A ferramenta organiza dados oficiais, carteiras persistidas, gráficos de monitoramento,
            simulações e documentação técnica em uma experiência única de análise.
          </div>
          <div class="about-grid">
            <div class="about-card">
              <div class="about-card-title">Dados oficiais</div>
              <div class="about-card-body">Rotinas voltadas ao uso dos informes estruturados, com rastreabilidade dos campos e validações de consistência.</div>
            </div>
            <div class="about-card">
              <div class="about-card-title">Análise de carteira</div>
              <div class="about-card-body">Visões consolidadas e individuais para PL, subordinação, inadimplência, cobertura, aging, roll rates e duration.</div>
            </div>
            <div class="about-card">
              <div class="about-card-title">Modelagem</div>
              <div class="about-card-body">Simulador econômico-financeiro de FIDC, com premissas explícitas e documentação da mecânica de cálculo.</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_development_investment_section()
