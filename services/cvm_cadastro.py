"""CVM Dados Abertos - cadastro de fundos e classes.

Fontes oficiais vigentes usadas como complemento estruturado do Informe Mensal:

1. fi-cad / cad_fi.csv
   Cadastro legado de fundos nao adaptados a RCVM 175.
   Expondo, por fundo: administrador, gestor e custodiante.

2. fi-cad / registro_fundo_classe.zip
   Cadastro vigente de fundos, classes e subclasses.
   Expondo:
   - registro_fundo.csv  -> administrador e gestor por fundo
   - registro_classe.csv -> custodiante por classe

As funcoes abaixo mantem a interface simples do projeto, mas registram a
proveniencia de cada campo para permitir uso auditavel na camada do dashboard.
"""

from __future__ import annotations

import io
import hashlib
import time
from pathlib import Path
import re
import urllib.error
import urllib.request
import zipfile
from functools import lru_cache
from typing import Any

import pandas as pd


_CAD_FI_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv"
_REGISTRO_FUNDO_CLASSE_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"
_REQUEST_TIMEOUT = 20
_DISK_CACHE_DIR = Path(".cache/cvm-cadastro")
_DISK_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_ACTIVE_STATUSES = {"EM FUNCIONAMENTO NORMAL", "Em Funcionamento Normal"}


def _strip_digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper() in {"", "N/A", "NAO", "NÃO", "NAO INFORMADO", "NÃO INFORMADO"}:
        return ""
    return text


def _download_bytes(url: str, *, allow_network: bool = True) -> bytes | None:
    cached = _read_cached_bytes(url, max_age_seconds=_DISK_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached
    stale_cached = _read_cached_bytes(url, max_age_seconds=None)
    if not allow_network:
        return stale_cached
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "fidc-dashboard/1.0 (dados.cvm.gov.br open data)"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            payload = resp.read()
            _write_cached_bytes(url, payload)
            return payload
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        except Exception:  # noqa: BLE001
            pass
        return stale_cached
    except Exception:  # noqa: BLE001
        return stale_cached


def _cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha256(str(url).encode("utf-8")).hexdigest()
    return _DISK_CACHE_DIR / f"{digest}.bin"


def _read_cached_bytes(url: str, *, max_age_seconds: int | None) -> bytes | None:
    path = _cache_path_for_url(url)
    try:
        if not path.exists() or not path.is_file():
            return None
        if max_age_seconds is not None:
            age_seconds = time.time() - path.stat().st_mtime
            if age_seconds > max_age_seconds:
                return None
        return path.read_bytes()
    except OSError:
        return None


def _write_cached_bytes(url: str, payload: bytes) -> None:
    try:
        _DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path_for_url(url).write_bytes(payload)
    except OSError:
        return


@lru_cache(maxsize=1)
def _load_fi_cad_legacy(allow_network: bool = True) -> pd.DataFrame | None:
    raw = _download_bytes(_CAD_FI_URL, allow_network=allow_network)
    if raw is None:
        return None
    try:
        df = pd.read_csv(
            io.BytesIO(raw),
            sep=";",
            encoding="latin-1",
            dtype=str,
            keep_default_na=False,
        )
    except Exception:  # noqa: BLE001
        return None
    df.columns = [str(column).strip() for column in df.columns]
    return df


@lru_cache(maxsize=1)
def _load_registro_fundo_classe(allow_network: bool = True) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    raw = _download_bytes(_REGISTRO_FUNDO_CLASSE_URL, allow_network=allow_network)
    if raw is None:
        return None, None
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        with archive.open("registro_fundo.csv") as fundo_file:
            fundo_df = pd.read_csv(
                fundo_file,
                sep=";",
                encoding="latin-1",
                dtype=str,
                keep_default_na=False,
            )
        with archive.open("registro_classe.csv") as classe_file:
            classe_df = pd.read_csv(
                classe_file,
                sep=";",
                encoding="latin-1",
                dtype=str,
                keep_default_na=False,
            )
    except Exception:  # noqa: BLE001
        return None, None
    fundo_df.columns = [str(column).strip() for column in fundo_df.columns]
    classe_df.columns = [str(column).strip() for column in classe_df.columns]
    return fundo_df, classe_df


def _ensure_norm_column(df: pd.DataFrame, source_column: str, norm_column: str) -> pd.DataFrame:
    if source_column not in df.columns:
        return df
    if norm_column not in df.columns:
        df[norm_column] = df[source_column].map(_strip_digits)
    return df


def _prefer_best_row(
    frame: pd.DataFrame,
    *,
    situation_column: str | None,
    preferred_columns: list[str],
    date_columns: list[str],
) -> pd.Series | None:
    if frame.empty:
        return None
    working = frame.copy()
    if situation_column and situation_column in working.columns:
        active = working[working[situation_column].astype(str).str.strip().isin(_ACTIVE_STATUSES)].copy()
        if not active.empty:
            working = active
    working["_filled_score"] = 0
    for column in preferred_columns:
        if column in working.columns:
            working["_filled_score"] = working["_filled_score"] + (
                working[column].astype(str).str.strip() != ""
            ).astype(int)
    for idx, column in enumerate(date_columns, start=1):
        if column in working.columns:
            parsed = pd.to_datetime(working[column], errors="coerce")
            working[f"_date_sort_{idx}"] = parsed
        else:
            working[f"_date_sort_{idx}"] = pd.NaT
    sort_columns = ["_filled_score"] + [f"_date_sort_{idx}" for idx in range(1, len(date_columns) + 1)]
    working = working.sort_values(sort_columns, ascending=False, na_position="last")
    return working.iloc[0]


def _match_fi_cad_legacy(cnpj_fundo: str, *, allow_network: bool = True) -> pd.Series | None:
    cnpj_digits = _strip_digits(cnpj_fundo)
    if len(cnpj_digits) != 14:
        return None
    df = _load_fi_cad_legacy(allow_network)
    if df is None or df.empty or "CNPJ_FUNDO" not in df.columns:
        return None
    df = _ensure_norm_column(df, "CNPJ_FUNDO", "_cnpj_fundo_norm")
    fidc_df = df[df["TP_FUNDO"].astype(str).str.contains("FIDC", case=False, na=False)].copy()
    match = fidc_df[fidc_df["_cnpj_fundo_norm"] == cnpj_digits].copy()
    return _prefer_best_row(
        match,
        situation_column="SIT",
        preferred_columns=[
            "CNPJ_ADMIN",
            "ADMIN",
            "CPF_CNPJ_GESTOR",
            "GESTOR",
            "CNPJ_CUSTODIANTE",
            "CUSTODIANTE",
        ],
        date_columns=["DT_PATRIM_LIQ", "DT_INI_SIT", "DT_REG"],
    )


def _match_registro_fundo(cnpj_fundo: str, *, allow_network: bool = True) -> pd.Series | None:
    cnpj_digits = _strip_digits(cnpj_fundo)
    if len(cnpj_digits) != 14:
        return None
    fundo_df, _ = _load_registro_fundo_classe(allow_network)
    if fundo_df is None or fundo_df.empty or "CNPJ_Fundo" not in fundo_df.columns:
        return None
    fundo_df = _ensure_norm_column(fundo_df, "CNPJ_Fundo", "_cnpj_fundo_norm")
    fidc_df = fundo_df[fundo_df["Tipo_Fundo"].astype(str).str.contains("FIDC", case=False, na=False)].copy()
    match = fidc_df[fidc_df["_cnpj_fundo_norm"] == cnpj_digits].copy()
    return _prefer_best_row(
        match,
        situation_column="Situacao",
        preferred_columns=[
            "CNPJ_Administrador",
            "Administrador",
            "CPF_CNPJ_Gestor",
            "Gestor",
        ],
        date_columns=["Data_Inicio_Situacao", "Data_Registro", "Data_Adaptacao_RCVM175"],
    )


def _match_registro_classe(cnpj_classe: str, *, allow_network: bool = True) -> pd.Series | None:
    cnpj_digits = _strip_digits(cnpj_classe)
    if len(cnpj_digits) != 14:
        return None
    _, classe_df = _load_registro_fundo_classe(allow_network)
    if classe_df is None or classe_df.empty or "CNPJ_Classe" not in classe_df.columns:
        return None
    classe_df = _ensure_norm_column(classe_df, "CNPJ_Classe", "_cnpj_classe_norm")
    fidc_df = classe_df[
        classe_df["Tipo_Classe"].astype(str).str.contains("FIDC", case=False, na=False)
    ].copy()
    match = fidc_df[fidc_df["_cnpj_classe_norm"] == cnpj_digits].copy()
    return _prefer_best_row(
        match,
        situation_column="Situacao",
        preferred_columns=["CNPJ_Custodiante", "Custodiante"],
        date_columns=["Data_Inicio_Situacao", "Data_Registro", "Data_Constituicao"],
    )


def _pick_value(
    primary_row: pd.Series | None,
    primary_name_col: str,
    primary_cnpj_col: str,
    *,
    primary_source: str,
    fallback_row: pd.Series | None = None,
    fallback_name_col: str = "",
    fallback_cnpj_col: str = "",
    fallback_source: str = "",
) -> tuple[str, str, str]:
    if primary_row is not None:
        name = _clean(primary_row.get(primary_name_col, ""))
        cnpj = _strip_digits(primary_row.get(primary_cnpj_col, ""))
        if name or cnpj:
            return name, cnpj, primary_source
    if fallback_row is not None:
        name = _clean(fallback_row.get(fallback_name_col, ""))
        cnpj = _strip_digits(fallback_row.get(fallback_cnpj_col, ""))
        if name or cnpj:
            return name, cnpj, fallback_source
    return "", "", ""


def fetch_fidc_participantes(
    cnpj_fundo: str,
    cnpj_classe: str | None = None,
    *,
    allow_network: bool = True,
) -> dict[str, str]:
    """Look up administrador, gestor and custodiante from the official CVM cadastro.

    Returns empty strings when the relevant source is unavailable or the field is
    not structurally covered for the requested fund/class.
    """

    empty: dict[str, str] = {
        "nm_admin": "",
        "nm_gestor": "",
        "nm_custodiante": "",
        "cnpj_admin": "",
        "cnpj_gestor": "",
        "cnpj_custodiante": "",
        "fonte_admin": "",
        "fonte_gestor": "",
        "fonte_custodiante": "",
    }

    if len(_strip_digits(cnpj_fundo)) != 14:
        return empty

    registro_fundo = _match_registro_fundo(cnpj_fundo, allow_network=allow_network)
    legacy_fundo = _match_fi_cad_legacy(cnpj_fundo, allow_network=allow_network)
    registro_classe = _match_registro_classe(cnpj_classe or "", allow_network=allow_network)

    nm_admin, cnpj_admin, fonte_admin = _pick_value(
        registro_fundo,
        "Administrador",
        "CNPJ_Administrador",
        primary_source="fi_cad_registro_fundo",
        fallback_row=legacy_fundo,
        fallback_name_col="ADMIN",
        fallback_cnpj_col="CNPJ_ADMIN",
        fallback_source="fi_cad_legado_fundo",
    )
    nm_gestor, cnpj_gestor, fonte_gestor = _pick_value(
        registro_fundo,
        "Gestor",
        "CPF_CNPJ_Gestor",
        primary_source="fi_cad_registro_fundo",
        fallback_row=legacy_fundo,
        fallback_name_col="GESTOR",
        fallback_cnpj_col="CPF_CNPJ_GESTOR",
        fallback_source="fi_cad_legado_fundo",
    )
    nm_custodiante, cnpj_custodiante, fonte_custodiante = _pick_value(
        registro_classe,
        "Custodiante",
        "CNPJ_Custodiante",
        primary_source="fi_cad_registro_classe",
        fallback_row=legacy_fundo,
        fallback_name_col="CUSTODIANTE",
        fallback_cnpj_col="CNPJ_CUSTODIANTE",
        fallback_source="fi_cad_legado_fundo",
    )

    return {
        "nm_admin": nm_admin,
        "nm_gestor": nm_gestor,
        "nm_custodiante": nm_custodiante,
        "cnpj_admin": cnpj_admin,
        "cnpj_gestor": cnpj_gestor,
        "cnpj_custodiante": cnpj_custodiante,
        "fonte_admin": fonte_admin,
        "fonte_gestor": fonte_gestor,
        "fonte_custodiante": fonte_custodiante,
    }


def _catalog_from_legacy() -> pd.DataFrame:
    df = _load_fi_cad_legacy()
    if df is None or df.empty:
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])
    frame = df[df["TP_FUNDO"].astype(str).str.contains("FIDC", case=False, na=False)].copy()
    if frame.empty:
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])
    output = pd.DataFrame(
        {
            "cnpj_fundo": frame["CNPJ_FUNDO"].map(_strip_digits),
            "nome_fundo": frame["DENOM_SOCIAL"].map(_clean),
            "situacao": frame["SIT"].map(_clean),
        }
    )
    output = output[output["cnpj_fundo"].str.len() == 14].copy()
    output = output[output["nome_fundo"].astype(str).str.strip() != ""].copy()
    return output


def _catalog_from_registro() -> pd.DataFrame:
    fundo_df, _ = _load_registro_fundo_classe()
    if fundo_df is None or fundo_df.empty:
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])
    frame = fundo_df[fundo_df["Tipo_Fundo"].astype(str).str.contains("FIDC", case=False, na=False)].copy()
    if frame.empty:
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])
    output = pd.DataFrame(
        {
            "cnpj_fundo": frame["CNPJ_Fundo"].map(_strip_digits),
            "nome_fundo": frame["Denominacao_Social"].map(_clean),
            "situacao": frame["Situacao"].map(_clean),
        }
    )
    output = output[output["cnpj_fundo"].str.len() == 14].copy()
    output = output[output["nome_fundo"].astype(str).str.strip() != ""].copy()
    return output


def list_fidc_catalog() -> pd.DataFrame:
    """Return a searchable catalog of FIDCs from the official CVM cadastro."""

    frames = [_catalog_from_registro(), _catalog_from_legacy()]
    output = pd.concat(frames, ignore_index=True)
    if output.empty:
        return pd.DataFrame(columns=["cnpj_fundo", "nome_fundo", "situacao"])
    output["situacao_ativa"] = output["situacao"].isin(_ACTIVE_STATUSES).astype(int)
    output["nome_len"] = output["nome_fundo"].astype(str).str.len()
    output = output.sort_values(
        ["cnpj_fundo", "situacao_ativa", "nome_len", "nome_fundo"],
        ascending=[True, False, False, True],
        na_position="last",
    )
    output = output.drop_duplicates(subset=["cnpj_fundo"], keep="first")
    output = output.drop(columns=["situacao_ativa", "nome_len"])
    return output.sort_values(["nome_fundo", "cnpj_fundo"]).reset_index(drop=True)
