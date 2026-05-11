from __future__ import annotations

import csv
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import re
from typing import Sequence

from openpyxl import Workbook
import pandas as pd


WIDE_META_COLUMNS = [
    "bloco",
    "sub_bloco",
    "tag",
    "tag_path",
    "descricao",
]

_ILLEGAL_EXCEL_CHARS_RE = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]")
_NUMERIC_CELL_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def append_dataframe_to_csv(
    df: pd.DataFrame,
    path: Path,
    *,
    columns: Sequence[str] | None = None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered_columns = list(columns or df.columns.tolist())
    if not ordered_columns:
        raise ValueError("columns must not be empty when appending a dataframe to CSV")

    if df.empty:
        if not path.exists():
            pd.DataFrame(columns=ordered_columns).to_csv(path, index=False)
        return 0

    normalized_df = df.reindex(columns=ordered_columns)
    normalized_df.to_csv(path, mode="a", index=False, header=not path.exists())
    return int(len(normalized_df))


def build_wide_csv_from_period_csvs(
    period_scalar_paths: dict[str, Path],
    competencias_ordenadas: list[str],
    output_path: Path,
    workspace_dir: Path,
) -> int:
    manifest_df = _build_manifest_frame(period_scalar_paths)
    manifest_columns = WIDE_META_COLUMNS + ["ordem_hierarquica"]
    manifest_path = workspace_dir / "wide_manifest.csv"
    if manifest_df.empty:
        pd.DataFrame(columns=WIDE_META_COLUMNS + competencias_ordenadas).to_csv(output_path, index=False)
        pd.DataFrame(columns=manifest_columns).to_csv(manifest_path, index=False)
        return 0

    manifest_df.to_csv(manifest_path, index=False)
    prepared_period_paths = _prepare_period_value_files(
        manifest_df=manifest_df,
        period_scalar_paths=period_scalar_paths,
        competencias_ordenadas=competencias_ordenadas,
        workspace_dir=workspace_dir,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with ExitStack() as stack:
        output_fp = stack.enter_context(output_path.open("w", encoding="utf-8", newline=""))
        writer = csv.writer(output_fp)
        writer.writerow(WIDE_META_COLUMNS + competencias_ordenadas)

        reader_specs: list[tuple[str, csv.DictReader]] = []
        for competencia in competencias_ordenadas:
            reader_fp = stack.enter_context(prepared_period_paths[competencia].open("r", encoding="utf-8", newline=""))
            reader_specs.append((competencia, csv.DictReader(reader_fp)))

        for rows in zip(*(reader for _, reader in reader_specs), strict=True):
            base_row = rows[0]
            meta_key = tuple(base_row[column] for column in WIDE_META_COLUMNS)
            output_row = list(meta_key)
            for (competencia, _), period_row in zip(reader_specs, rows, strict=True):
                current_key = tuple(period_row[column] for column in WIDE_META_COLUMNS)
                if current_key != meta_key:
                    raise ValueError("Prepared period files lost row alignment while assembling the wide CSV")
                output_row.append(period_row.get(competencia, ""))
            writer.writerow(output_row)
            row_count += 1
    return row_count


def build_excel_from_csvs(
    *,
    wide_csv_path: Path,
    listas_csv_path: Path,
    docs_csv_path: Path,
    audit_csv_path: Path,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    _append_csv_sheet(workbook, "informes_campos", wide_csv_path)
    _append_csv_sheet(workbook, "estruturas_lista", listas_csv_path)
    _append_csv_sheet(workbook, "documentos", docs_csv_path)
    _append_csv_sheet(workbook, "auditoria", audit_csv_path)
    workbook.save(output_path)


def build_wide_dataset(contas_df: pd.DataFrame, competencias_ordenadas: list[str]) -> pd.DataFrame:
    if contas_df.empty:
        return pd.DataFrame(columns=WIDE_META_COLUMNS)

    base = contas_df.copy()
    ordem_por_caminho = (
        base.groupby("tag_path", dropna=False)["ordem_xml"].min().rename("ordem_hierarquica").reset_index()
    )

    pivot = (
        base.pivot_table(
            index=WIDE_META_COLUMNS,
            columns="competencia",
            values="valor_excel",
            aggfunc="first",
            dropna=False,
        )
        .reset_index()
        .merge(ordem_por_caminho, on="tag_path", how="left")
        .sort_values(["ordem_hierarquica", "bloco", "sub_bloco", "tag_path"], kind="stable")
    )

    for competencia in competencias_ordenadas:
        if competencia not in pivot.columns:
            pivot[competencia] = pd.NA

    ordered_columns = WIDE_META_COLUMNS + competencias_ordenadas
    return pivot[ordered_columns]


def build_excel_bytes(
    wide_df: pd.DataFrame,
    listas_df: pd.DataFrame,
    docs_df: pd.DataFrame,
    audit_df: pd.DataFrame,
) -> bytes:
    def _sanitize_for_excel(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        safe_df = df.copy()
        object_columns = safe_df.select_dtypes(include=["object", "string"]).columns
        for column in object_columns:
            safe_df[column] = safe_df[column].map(
                lambda value: _ILLEGAL_EXCEL_CHARS_RE.sub("", value) if isinstance(value, str) else value
            )
        return safe_df

    safe_wide_df = _sanitize_for_excel(wide_df)
    safe_listas_df = _sanitize_for_excel(listas_df)
    safe_docs_df = _sanitize_for_excel(docs_df)
    safe_audit_df = _sanitize_for_excel(audit_df)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        safe_wide_df.to_excel(writer, sheet_name="informes_campos", index=False)
        safe_listas_df.to_excel(writer, sheet_name="estruturas_lista", index=False)
        safe_docs_df.to_excel(writer, sheet_name="documentos", index=False)
        safe_audit_df.to_excel(writer, sheet_name="auditoria", index=False)
    return output.getvalue()


def _build_manifest_frame(period_scalar_paths: dict[str, Path]) -> pd.DataFrame:
    manifest: dict[tuple[str, ...], int] = {}
    usecols = WIDE_META_COLUMNS + ["ordem_xml"]
    key_dtypes = {column: "string" for column in WIDE_META_COLUMNS}
    for csv_path in period_scalar_paths.values():
        if not csv_path.exists():
            continue
        period_df = pd.read_csv(
            csv_path,
            usecols=usecols,
            dtype=key_dtypes,
            keep_default_na=False,
        )
        if period_df.empty:
            continue
        period_df["ordem_xml"] = pd.to_numeric(period_df["ordem_xml"], errors="coerce")
        for row in period_df.itertuples(index=False):
            key = tuple("" if pd.isna(getattr(row, column)) else str(getattr(row, column)) for column in WIDE_META_COLUMNS)
            raw_order = getattr(row, "ordem_xml")
            order = int(raw_order) if pd.notna(raw_order) else 10**12
            current = manifest.get(key)
            if current is None or order < current:
                manifest[key] = order

    if not manifest:
        return pd.DataFrame(columns=WIDE_META_COLUMNS + ["ordem_hierarquica"])

    rows = []
    for key, order in manifest.items():
        row = {column: value for column, value in zip(WIDE_META_COLUMNS, key, strict=True)}
        row["ordem_hierarquica"] = order
        rows.append(row)
    manifest_df = pd.DataFrame(rows, columns=WIDE_META_COLUMNS + ["ordem_hierarquica"])
    return manifest_df.sort_values(
        ["ordem_hierarquica", "bloco", "sub_bloco", "tag_path"],
        kind="stable",
    ).reset_index(drop=True)


def _prepare_period_value_files(
    *,
    manifest_df: pd.DataFrame,
    period_scalar_paths: dict[str, Path],
    competencias_ordenadas: list[str],
    workspace_dir: Path,
) -> dict[str, Path]:
    manifest_meta_df = manifest_df[WIDE_META_COLUMNS].copy()
    prepared_paths: dict[str, Path] = {}
    key_dtypes = {column: "string" for column in WIDE_META_COLUMNS}
    for competencia in competencias_ordenadas:
        period_path = period_scalar_paths.get(competencia)
        target_path = workspace_dir / f"wide_period_{_slugify_filename(competencia)}.csv"
        if period_path is None or not period_path.exists():
            prepared_df = manifest_meta_df.copy()
            prepared_df[competencia] = pd.NA
        else:
            period_df = pd.read_csv(
                period_path,
                usecols=WIDE_META_COLUMNS + ["valor_excel"],
                dtype=key_dtypes,
                keep_default_na=False,
            )
            period_df = period_df.drop_duplicates(subset=WIDE_META_COLUMNS, keep="first")
            prepared_df = manifest_meta_df.merge(period_df, on=WIDE_META_COLUMNS, how="left")
            prepared_df = prepared_df[WIDE_META_COLUMNS + ["valor_excel"]].rename(columns={"valor_excel": competencia})
        prepared_df.to_csv(target_path, index=False)
        prepared_paths[competencia] = target_path
    return prepared_paths


def _append_csv_sheet(workbook: Workbook, sheet_name: str, csv_path: Path) -> None:
    worksheet = workbook.create_sheet(title=sheet_name)
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.reader(fp)
        for row in reader:
            worksheet.append([_sanitize_excel_cell(value) for value in row])


def _sanitize_excel_cell(value: str) -> object:
    if value is None:
        return None
    cleaned = _ILLEGAL_EXCEL_CHARS_RE.sub("", value)
    if cleaned == "":
        return None
    if _NUMERIC_CELL_RE.fullmatch(cleaned):
        if "." in cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return cleaned
        try:
            return int(cleaned)
        except ValueError:
            return cleaned
    return cleaned


def _slugify_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return normalized.strip("._") or "periodo"
