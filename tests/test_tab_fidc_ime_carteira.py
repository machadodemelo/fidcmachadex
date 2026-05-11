from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.portfolio_store import PortfolioFund, PortfolioRecord
from tabs.tab_fidc_ime_carteira import (
    _apply_pending_portfolio_selection,
    _build_portfolio_selector_label_lookup,
    _build_loaded_dashboards_by_cnpj,
    _execute_portfolio_load_for_funds,
    _normalize_portfolio_editor_mode,
    _queue_portfolio_selection,
    _sync_portfolio_fund_names_from_results,
)


class _DummyProgress:
    def progress(self, *_args, **_kwargs) -> None:
        return None

    def empty(self) -> None:
        return None


class _DummyStatus:
    def caption(self, *_args, **_kwargs) -> None:
        return None

    def empty(self) -> None:
        return None


class TabFidcImeCarteiraTests(unittest.TestCase):
    def test_build_portfolio_selector_label_lookup_disambiguates_duplicate_name_and_basket(self) -> None:
        portfolio_a = PortfolioRecord(
            id="57f3418c1e9341e79edeef6086b8c25d",
            name="Mercado Credito Soma",
            funds=(
                PortfolioFund(cnpj="33254370000104", display_name="FIDC A"),
                PortfolioFund(cnpj="37511828000114", display_name="FIDC B"),
                PortfolioFund(cnpj="41970012000126", display_name="FIDC C"),
            ),
            created_at="2026-04-15T00:00:00Z",
            updated_at="2026-04-15T00:00:00Z",
        )
        portfolio_b = PortfolioRecord(
            id="4220dda141ea442abd86a6ee11ed249f",
            name="Mercado Credito Soma",
            funds=(
                PortfolioFund(cnpj="41970012000126", display_name="FIDC C"),
                PortfolioFund(cnpj="37511828000114", display_name="FIDC B"),
                PortfolioFund(cnpj="33254370000104", display_name="FIDC A"),
            ),
            created_at="2026-04-16T00:00:00Z",
            updated_at="2026-04-16T00:00:00Z",
        )

        labels = _build_portfolio_selector_label_lookup([portfolio_a, portfolio_b])

        self.assertEqual(
            "Mercado Credito Soma · 3 fundo(s) · ID 57f3418c",
            labels[portfolio_a.id],
        )
        self.assertEqual(
            "Mercado Credito Soma · 3 fundo(s) · ID 4220dda1",
            labels[portfolio_b.id],
        )

    def test_queue_and_apply_pending_portfolio_selection(self) -> None:
        with patch.dict("tabs.tab_fidc_ime_carteira.st.session_state", {}, clear=True):
            _queue_portfolio_selection("portfolio-2")
            _apply_pending_portfolio_selection()

            from tabs.tab_fidc_ime_carteira import st  # local import to read patched state

            self.assertEqual("portfolio-2", st.session_state.get("ime_portfolio_active_id"))
            self.assertNotIn("_ime_portfolio_active_id_pending", st.session_state)

    def test_apply_pending_portfolio_selection_can_clear_active_value(self) -> None:
        with patch.dict(
            "tabs.tab_fidc_ime_carteira.st.session_state",
            {"ime_portfolio_active_id": "portfolio-1"},
            clear=True,
        ):
            _queue_portfolio_selection(None, clear=True)
            _apply_pending_portfolio_selection()

            from tabs.tab_fidc_ime_carteira import st  # local import to read patched state

            self.assertNotIn("ime_portfolio_active_id", st.session_state)

    def test_normalize_portfolio_editor_mode_distinguishes_create_and_edit(self) -> None:
        self.assertEqual("create", _normalize_portfolio_editor_mode(None, has_portfolios=False))
        self.assertEqual("edit", _normalize_portfolio_editor_mode(None, has_portfolios=True))
        self.assertEqual("create", _normalize_portfolio_editor_mode("create", has_portfolios=True))

    def test_sync_portfolio_fund_names_from_results_persists_resolved_name(self) -> None:
        portfolio = PortfolioRecord(
            id="portfolio-1",
            name="Carteira Teste",
            funds=(PortfolioFund(cnpj="12345678000199", display_name="12345678000199"),),
            created_at="2026-04-15T00:00:00Z",
            updated_at="2026-04-15T00:00:00Z",
        )
        results = {
            "12345678000199": {
                "context": {
                    "portfolio_fund_name_resolved": "FIDC Resolvido",
                }
            }
        }

        with patch("tabs.tab_fidc_ime_carteira.save_portfolio_record", side_effect=lambda record: record) as mocked_save:
            updated = _sync_portfolio_fund_names_from_results(
                selected_portfolio=portfolio,
                results=results,
            )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual("FIDC Resolvido", updated.funds[0].display_name)
        mocked_save.assert_called_once()

    def test_sync_portfolio_fund_names_ignores_predictable_duplicate_selection(self) -> None:
        portfolio = PortfolioRecord(
            id="portfolio-1",
            name="Carteira Teste",
            funds=(PortfolioFund(cnpj="12345678000199", display_name="12345678000199"),),
            created_at="2026-04-15T00:00:00Z",
            updated_at="2026-04-15T00:00:00Z",
        )
        results = {
            "12345678000199": {
                "context": {
                    "portfolio_fund_name_resolved": "FIDC Resolvido",
                }
            }
        }

        with patch(
            "tabs.tab_fidc_ime_carteira.save_portfolio_record",
            side_effect=ValueError("Já existe uma seleção idêntica salva com este nome e a mesma cesta de fundos (57f3418c)."),
        ):
            updated = _sync_portfolio_fund_names_from_results(
                selected_portfolio=portfolio,
                results=results,
            )

        self.assertIsNone(updated)

    def test_execute_portfolio_load_for_funds_does_not_require_retry_results_when_no_retry(self) -> None:
        portfolio = PortfolioRecord(
            id="portfolio-1",
            name="Carteira Teste",
            funds=(PortfolioFund(cnpj="12345678000199", display_name="FIDC A"),),
            created_at="2026-04-15T00:00:00Z",
            updated_at="2026-04-15T00:00:00Z",
        )
        period = SimpleNamespace(
            month_count=12,
            cache_key="period-1",
            label="12 meses",
            mode="preset",
            start_month=SimpleNamespace(isoformat=lambda: "2026-01-01"),
            end_month=SimpleNamespace(isoformat=lambda: "2026-12-01"),
            preset_months=12,
        )
        initial_results = {
            "12345678000199": {
                "result": object(),
                "context": {"portfolio_fund_name_resolved": "FIDC A"},
            }
        }

        with (
            patch("tabs.tab_fidc_ime_carteira.st.progress", return_value=_DummyProgress()),
            patch("tabs.tab_fidc_ime_carteira.st.empty", return_value=_DummyStatus()),
            patch("tabs.tab_fidc_ime_carteira._portfolio_worker_count", return_value=1),
            patch("tabs.tab_fidc_ime_carteira._load_portfolio_funds_batch", return_value=initial_results),
            patch("tabs.tab_fidc_ime_carteira._sync_portfolio_fund_names_from_results", return_value=None),
            patch("tabs.tab_fidc_ime_carteira._get_portfolio_runtime_state", return_value={}),
            patch("tabs.tab_fidc_ime_carteira._save_portfolio_runtime_state"),
        ):
            _execute_portfolio_load_for_funds(
                selected_portfolio=portfolio,
                period=period,
                funds=portfolio.funds,
                existing_results=None,
            )

    def test_build_loaded_dashboards_by_cnpj_skips_funds_with_dashboard_error(self) -> None:
        portfolio = PortfolioRecord(
            id="portfolio-1",
            name="Carteira Teste",
            funds=(
                PortfolioFund(cnpj="12345678000199", display_name="FIDC A"),
                PortfolioFund(cnpj="22345678000199", display_name="FIDC B"),
            ),
            created_at="2026-04-15T00:00:00Z",
            updated_at="2026-04-15T00:00:00Z",
        )
        fake_result = SimpleNamespace(
            wide_csv_path=Path("wide.csv"),
            listas_csv_path=Path("listas.csv"),
            docs_csv_path=Path("docs.csv"),
        )
        results = {
            "12345678000199": {"result": fake_result, "context": {}},
            "22345678000199": {"result": fake_result, "context": {}},
        }

        with patch(
            "tabs.tab_fidc_ime_carteira.ime_tab._load_dashboard_data",
            side_effect=[object(), RuntimeError("quebra de teste")],
        ):
            dashboards, errors = _build_loaded_dashboards_by_cnpj(
                selected_portfolio=portfolio,
                results=results,
            )

        self.assertEqual(1, len(dashboards))
        self.assertEqual(1, len(errors))
        self.assertIn("22345678000199", errors)


if __name__ == "__main__":
    unittest.main()
