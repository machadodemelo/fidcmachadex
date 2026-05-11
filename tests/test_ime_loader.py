from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from services.ime_loader import load_or_extract_informe, peek_cached_informe
from services.fundonet_service import InformeMensalResult


class _FakeInformeService:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.run_calls = 0

    def run(self, cnpj_fundo, data_inicial, data_final, *, progress_callback=None):  # noqa: ANN001
        self.run_calls += 1
        workspace_dir = self.workspace_root / f"run-{self.run_calls}"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        docs_df = pd.DataFrame([{"documento_id": "1", "competencia": "01/2026", "processamento": "ok", "erro_processamento": ""}])
        audit_df = pd.DataFrame([{"etapa": "teste", "status": "ok", "detalhe": "cached"}])
        contas_df = pd.DataFrame([{"cnpj_fundo": cnpj_fundo, "valor_num": 100.0}])
        listas_df = pd.DataFrame([{"documento_id": "1", "valor_num": 50.0}])
        wide_df = pd.DataFrame([{"tag_path": "DOC", "01/2026": "100"}])

        docs_csv = workspace_dir / "documentos_filtrados.csv"
        contas_csv = workspace_dir / "informes_tidy.csv"
        listas_csv = workspace_dir / "estruturas_lista.csv"
        wide_csv = workspace_dir / "informes_wide.csv"
        excel_path = workspace_dir / "informes_wide.xlsx"
        audit_csv = workspace_dir / "audit_log.csv"
        audit_json = workspace_dir / "audit_log.json"

        docs_df.to_csv(docs_csv, index=False)
        contas_df.to_csv(contas_csv, index=False)
        listas_df.to_csv(listas_csv, index=False)
        wide_df.to_csv(wide_csv, index=False)
        audit_df.to_csv(audit_csv, index=False)
        audit_json.write_text("{}", encoding="utf-8")
        excel_path.write_bytes(b"excel")

        return InformeMensalResult(
            docs_df=docs_df,
            audit_df=audit_df,
            competencias=["01/2026"],
            workspace_dir=workspace_dir,
            docs_csv_path=docs_csv,
            contas_csv_path=contas_csv,
            listas_csv_path=listas_csv,
            wide_csv_path=wide_csv,
            excel_path=excel_path,
            audit_json_path=audit_json,
            contas_row_count=1,
            listas_row_count=1,
            wide_row_count=1,
        )


class ImeLoaderTests(unittest.TestCase):
    def test_loader_reuses_persisted_cache_between_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            service = _FakeInformeService(tmp_path / "workspace")
            cache_root = tmp_path / "cache"

            first = load_or_extract_informe(
                cnpj_fundo="12.345.678/0001-99",
                data_inicial=date(2026, 1, 1),
                data_final=date(2026, 4, 1),
                service=service,
                cache_root=cache_root,
            )
            second = load_or_extract_informe(
                cnpj_fundo="12.345.678/0001-99",
                data_inicial=date(2026, 1, 1),
                data_final=date(2026, 4, 1),
                service=service,
                cache_root=cache_root,
            )

            self.assertEqual(1, service.run_calls)
            self.assertEqual("miss", first.cache_status)
            self.assertEqual("hit", second.cache_status)
            self.assertTrue(second.result.wide_csv_path.exists())
            self.assertTrue(str(second.result.workspace_dir).startswith(str(cache_root.resolve())))

    def test_peek_cached_informe_reports_cache_availability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            service = _FakeInformeService(tmp_path / "workspace")
            cache_root = tmp_path / "cache"

            before = peek_cached_informe(
                cnpj_fundo="12.345.678/0001-99",
                data_inicial=date(2026, 1, 1),
                data_final=date(2026, 4, 1),
                cache_root=cache_root,
            )
            self.assertFalse(before.is_cached)

            load_or_extract_informe(
                cnpj_fundo="12.345.678/0001-99",
                data_inicial=date(2026, 1, 1),
                data_final=date(2026, 4, 1),
                service=service,
                cache_root=cache_root,
            )

            after = peek_cached_informe(
                cnpj_fundo="12.345.678/0001-99",
                data_inicial=date(2026, 1, 1),
                data_final=date(2026, 4, 1),
                cache_root=cache_root,
            )
            self.assertTrue(after.is_cached)
            self.assertTrue(after.manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
