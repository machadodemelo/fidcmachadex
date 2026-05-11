from __future__ import annotations

from html import escape

import streamlit as st

from services.fidc_book import FIDCBookIndex, FIDCBookPage, load_fidc_book_index


_BOOK_CSS = """
<style>
.fidc-book-header,
.fidc-book-header *,
.fidc-book-page-shell,
.fidc-book-page-shell *,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"],
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] * {
    font-family: 'IBM Plex Sans', sans-serif !important;
}

.fidc-book-header {
    margin: 0.15rem 0 1.1rem 0;
    padding-bottom: 0.9rem;
    border-bottom: 1px solid #ece5de;
}

.fidc-book-title {
    color: #12171d;
    font-size: 1.9rem;
    line-height: 1.02;
    letter-spacing: 0;
    font-weight: 600;
    margin: 0;
}

.fidc-book-subtitle {
    margin-top: 0.35rem;
    color: #68727d;
    font-size: 0.92rem;
    line-height: 1.4;
}

.fidc-book-page-shell {
    padding-bottom: 1.15rem;
    margin-bottom: 1.35rem;
    border-bottom: 1px solid #ece5de;
}

.fidc-book-page-section {
    color: #d35714;
    font-size: 0.76rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.45rem;
}

.fidc-book-page-title {
    color: #12171d;
    font-size: 2.45rem;
    line-height: 1.02;
    letter-spacing: 0;
    font-weight: 600;
    margin-bottom: 0.7rem;
}

.fidc-book-page-summary {
    max-width: 44rem;
    color: #59626d;
    font-size: 1.03rem;
    line-height: 1.68;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] {
    max-width: 48rem;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] h1 {
    display: none;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] h2 {
    color: #161c23;
    font-size: 1.5rem;
    line-height: 1.18;
    letter-spacing: 0;
    font-weight: 600;
    margin: 2rem 0 0.8rem 0;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] h3 {
    color: #d35714;
    font-size: 0.8rem;
    line-height: 1.2;
    letter-spacing: 0.08em;
    font-weight: 600;
    text-transform: uppercase;
    margin: 1.75rem 0 0.45rem 0;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] p,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] li,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] td,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] th {
    color: #27313b;
    font-size: 1rem;
    line-height: 1.76;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] p,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] ul,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] ol,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] table {
    margin-bottom: 1rem;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] ul,
div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] ol {
    padding-left: 1.15rem;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] strong {
    color: #141a20;
    font-weight: 600;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] table {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid #e9e3dd;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] thead tr {
    background: #f7f3ef;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] th {
    color: #a64916;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    text-align: left;
    padding: 0.75rem 0.85rem;
    border-bottom: 1px solid #e9e3dd;
}

div.element-container:has(.fidc-book-page-shell) + div.element-container [data-testid="stMarkdownContainer"] td {
    padding: 0.8rem 0.85rem;
    border-bottom: 1px solid #eee8e2;
    vertical-align: top;
}
</style>
"""


@st.cache_data(show_spinner=False)
def _load_index() -> FIDCBookIndex:
    return load_fidc_book_index()


def render_tab_fidc_book() -> None:
    index = _load_index()
    st.markdown(_BOOK_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="fidc-book-header">
          <div class="fidc-book-title">Glossário FIDCs</div>
          <div class="fidc-book-subtitle">Estrutura, risco e regulação</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    filtered_pages = index.search_pages(st.session_state.get("fidc_book_query", ""))
    filtered_page_ids = {page.page_id for page in filtered_pages}
    available_sections = tuple(
        section
        for section in index.sections
        if any(page.page_id in filtered_page_ids for page in section.pages)
    )
    if not available_sections:
        available_sections = index.sections

    query = st.text_input(
        "Buscar",
        key="fidc_book_query",
        placeholder="Buscar no glossário",
        label_visibility="collapsed",
    )

    filtered_pages = index.search_pages(query)
    filtered_page_ids = {page.page_id for page in filtered_pages}
    available_sections = tuple(
        section
        for section in index.sections
        if any(page.page_id in filtered_page_ids for page in section.pages)
    )
    if not available_sections:
        st.info("Nenhuma página encontrada.")
        return

    section_tabs = st.tabs([_section_tab_label(section) for section in available_sections])
    current_page = _current_page(index, filtered_page_ids)
    for section, tab in zip(available_sections, section_tabs, strict=False):
        with tab:
            section_pages = tuple(page for page in section.pages if page.page_id in filtered_page_ids)
            if not section_pages:
                st.info("Nenhuma página encontrada nesta seção.")
                continue
            page_lookup = {page.page_id: page for page in section_pages}
            default_page_id = current_page.page_id if current_page and current_page.page_id in page_lookup else section_pages[0].page_id
            if st.session_state.get(f"fidc_book_page_id::{section.section_id}") not in page_lookup:
                st.session_state[f"fidc_book_page_id::{section.section_id}"] = default_page_id
            left_col, right_col = st.columns([0.82, 2.38], gap="large")
            with left_col:
                page_id = st.radio(
                    "Páginas",
                    options=[page.page_id for page in section_pages],
                    index=[page.page_id for page in section_pages].index(default_page_id),
                    format_func=lambda value: page_lookup[value].title,
                    key=f"fidc_book_page_id::{section.section_id}",
                    label_visibility="collapsed",
                )
            with right_col:
                selected_page = page_lookup[page_id]
                _render_page(index, selected_page)


def _section_tab_label(section) -> str:
    if section.section_id == "comece-aqui":
        return "Guia de uso do glossário"
    return section.title


def _current_page(index: FIDCBookIndex, filtered_page_ids: set[str]) -> FIDCBookPage | None:
    page_id = st.session_state.get("fidc_book_page_id")
    if page_id and page_id in filtered_page_ids:
        try:
            return index.page_by_id(page_id)
        except KeyError:
            return None
    return None


def _render_page(index: FIDCBookIndex, page: FIDCBookPage) -> None:
    st.markdown(
        (
            '<div class="fidc-book-page-shell">'
            f'<div class="fidc-book-page-section">{escape(page.section_title)}</div>'
            f'<div class="fidc-book-page-title">{escape(page.title)}</div>'
            f'<div class="fidc-book-page-summary">{escape(page.summary)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    st.markdown(index.load_page_body(page))

    public_sources = [
        index.sources[source_id]
        for source_id in page.source_ids
        if source_id in index.sources and "http" in index.sources[source_id].location
    ]
    if public_sources:
        st.markdown('<div class="fidc-book-page-section">Fontes oficiais</div>', unsafe_allow_html=True)
        for source in public_sources:
            notes = f" — {source.notes}" if source.notes else ""
            st.markdown(f"- **{source.title}** · [link oficial]({source.location}){notes}")
