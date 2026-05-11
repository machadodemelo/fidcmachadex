from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd

from services.fundonet_service import InformeMensalResult, InformeMensalService


IME_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CachedInformeLoad:
    result: InformeMensalResult
    cache_key: str
    cache_dir: Path
    cache_status: str


@dataclass(frozen=True)
class CachedInformeProbe:
    cache_key: str
    cache_dir: Path
    manifest_path: Path
    is_cached: bool


def load_or_extract_informe(
    *,
    cnpj_fundo: str,
    data_inicial: date,
    data_final: date,
    service: InformeMensalService | None = None,
    cache_root: Path | None = None,
    progress_callback=None,  # noqa: ANN001
) -> CachedInformeLoad:
    cache_key = _build_cache_key(cnpj_fundo=cnpj_fundo, data_inicial=data_inicial, data_final=data_final)
    cache_dir = (cache_root or Path(".cache/fundonet-ime")).resolve() / cache_key
    manifest_path = cache_dir / "manifest.json"

    cached = _load_cached_result(cache_dir=cache_dir, manifest_path=manifest_path, cache_key=cache_key)
    if cached is not None:
        return cached

    runtime_service = service or InformeMensalService()
    fresh = runtime_service.run(
        cnpj_fundo=cnpj_fundo,
        data_inicial=data_inicial,
        data_final=data_final,
        progress_callback=progress_callback,
    )
    _persist_result_to_cache(
        result=fresh,
        cache_dir=cache_dir,
        manifest_path=manifest_path,
        cache_key=cache_key,
        cnpj_fundo=cnpj_fundo,
        data_inicial=data_inicial,
        data_final=data_final,
    )
    cached = _load_cached_result(cache_dir=cache_dir, manifest_path=manifest_path, cache_key=cache_key)
    if cached is None:
        raise RuntimeError("Falha ao reconstruir a extração a partir do cache persistido.")
    return CachedInformeLoad(
        result=cached.result,
        cache_key=cached.cache_key,
        cache_dir=cached.cache_dir,
        cache_status="miss",
    )


def peek_cached_informe(
    *,
    cnpj_fundo: str,
    data_inicial: date,
    data_final: date,
    cache_root: Path | None = None,
) -> CachedInformeProbe:
    cache_key = _build_cache_key(cnpj_fundo=cnpj_fundo, data_inicial=data_inicial, data_final=data_final)
    cache_dir = (cache_root or Path(".cache/fundonet-ime")).resolve() / cache_key
    manifest_path = cache_dir / "manifest.json"
    cached = _load_cached_result(cache_dir=cache_dir, manifest_path=manifest_path, cache_key=cache_key)
    return CachedInformeProbe(
        cache_key=cache_key,
        cache_dir=cache_dir,
        manifest_path=manifest_path,
        is_cached=cached is not None,
    )


def _build_cache_key(*, cnpj_fundo: str, data_inicial: date, data_final: date) -> str:
    payload = f"{''.join(ch for ch in str(cnpj_fundo) if ch.isdigit())}|{data_inicial.isoformat()}|{data_final.isoformat()}|{IME_CACHE_SCHEMA_VERSION}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _persist_result_to_cache(
    *,
    result: InformeMensalResult,
    cache_dir: Path,
    manifest_path: Path,
    cache_key: str,
    cnpj_fundo: str,
    data_inicial: date,
    data_final: date,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_map = {
        "docs_csv_path": result.docs_csv_path,
        "contas_csv_path": result.contas_csv_path,
        "listas_csv_path": result.listas_csv_path,
        "wide_csv_path": result.wide_csv_path,
        "excel_path": result.excel_path,
        "audit_json_path": result.audit_json_path,
        "audit_csv_path": result.workspace_dir / "audit_log.csv",
    }
    manifest_files: dict[str, str] = {}
    for logical_name, source_path in file_map.items():
        destination_name = source_path.name
        destination_path = cache_dir / destination_name
        shutil.copy2(source_path, destination_path)
        manifest_files[logical_name] = destination_name

    manifest = {
        "schema_version": IME_CACHE_SCHEMA_VERSION,
        "cache_key": cache_key,
        "cnpj_fundo": "".join(ch for ch in str(cnpj_fundo) if ch.isdigit()),
        "data_inicial": data_inicial.isoformat(),
        "data_final": data_final.isoformat(),
        "competencias": list(result.competencias),
        "contas_row_count": int(result.contas_row_count),
        "listas_row_count": int(result.listas_row_count),
        "wide_row_count": int(result.wide_row_count),
        "files": manifest_files,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cached_result(
    *,
    cache_dir: Path,
    manifest_path: Path,
    cache_key: str,
) -> CachedInformeLoad | None:
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if int(manifest.get("schema_version") or 0) != IME_CACHE_SCHEMA_VERSION:
        return None
    files = manifest.get("files") or {}
    required_keys = {
        "docs_csv_path",
        "contas_csv_path",
        "listas_csv_path",
        "wide_csv_path",
        "excel_path",
        "audit_json_path",
        "audit_csv_path",
    }
    if not required_keys.issubset(files):
        return None
    resolved_files = {name: cache_dir / str(filename) for name, filename in files.items()}
    if not all(path.exists() for path in resolved_files.values()):
        return None

    docs_df = pd.read_csv(resolved_files["docs_csv_path"], dtype=str, keep_default_na=False)
    audit_df = pd.read_csv(resolved_files["audit_csv_path"], dtype=str, keep_default_na=False)
    result = InformeMensalResult(
        docs_df=docs_df,
        audit_df=audit_df,
        competencias=list(manifest.get("competencias") or []),
        workspace_dir=cache_dir,
        docs_csv_path=resolved_files["docs_csv_path"],
        contas_csv_path=resolved_files["contas_csv_path"],
        listas_csv_path=resolved_files["listas_csv_path"],
        wide_csv_path=resolved_files["wide_csv_path"],
        excel_path=resolved_files["excel_path"],
        audit_json_path=resolved_files["audit_json_path"],
        contas_row_count=int(manifest.get("contas_row_count") or 0),
        listas_row_count=int(manifest.get("listas_row_count") or 0),
        wide_row_count=int(manifest.get("wide_row_count") or 0),
    )
    return CachedInformeLoad(
        result=result,
        cache_key=cache_key,
        cache_dir=cache_dir,
        cache_status="hit",
    )
