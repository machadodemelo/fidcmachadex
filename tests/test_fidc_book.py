from __future__ import annotations

import unittest

from services.fidc_book import load_fidc_book_index


class FIDCBookTests(unittest.TestCase):
    def test_load_book_index_exposes_sections_pages_and_sources(self) -> None:
        index = load_fidc_book_index()

        self.assertGreaterEqual(len(index.sections), 6)
        self.assertGreaterEqual(len(index.pages), 12)
        self.assertIn("rcvm_175_page", index.sources)
        self.assertIn("seller_regulamento", index.sources)
        self.assertGreaterEqual(len(index.concepts), 10)
        self.assertGreaterEqual(len(index.metrics), 8)
        self.assertGreaterEqual(len(index.reference_funds), 6)
        self.assertGreaterEqual(len(index.document_entries), 10)

    def test_load_page_markdown_reads_expected_content(self) -> None:
        index = load_fidc_book_index()
        page = index.page_by_id("overview")

        markdown = index.load_page_markdown(page)

        self.assertIn("Guia de uso deste glossário", markdown)
        self.assertIn("Informe Mensal Estruturado", markdown)

    def test_search_pages_matches_keywords(self) -> None:
        index = load_fidc_book_index()

        results = index.search_pages("subordinação cobertura")

        page_ids = {page.page_id for page in results}
        self.assertIn("metricas-estruturais", page_ids)

    def test_related_documents_and_concepts_are_available_for_metric_page(self) -> None:
        index = load_fidc_book_index()
        page = index.page_by_id("metricas-estruturais")

        concept_ids = {concept.concept_id for concept in index.related_concepts(page)}
        metric_ids = {metric.metric_id for metric in index.related_metrics(page)}
        document_ids = {entry.document_id for entry in index.related_documents(page)}

        self.assertIn("subordinacao", concept_ids)
        self.assertIn("indice_cobertura", metric_ids)
        self.assertIn("seller_relatorio", document_ids)
