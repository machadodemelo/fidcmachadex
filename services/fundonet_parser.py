from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any
import xml.etree.ElementTree as ET

import pandas as pd

from services.fundonet_errors import DocumentParseError
from services.fundonet_schema import resolve_schema_match


NUMERIC_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")

SCALAR_COLUMNS = [
    "documento_id",
    "competencia_xml",
    "xml_version",
    "bloco",
    "sub_bloco",
    "tag",
    "tag_path",
    "field_path",
    "schema_path_match",
    "schema_match_strategy",
    "descricao",
    "valor_raw",
    "valor_num",
    "valor_excel",
    "ordem_xml",
]

LIST_COLUMNS = [
    "documento_id",
    "competencia_xml",
    "xml_version",
    "bloco",
    "sub_bloco",
    "list_group_path",
    "list_item_path",
    "list_item_tag",
    "list_index",
    "tag",
    "tag_path",
    "field_path",
    "schema_path_match",
    "schema_match_strategy",
    "descricao",
    "valor_raw",
    "valor_num",
    "valor_excel",
    "ordem_xml",
]


@dataclass(frozen=True)
class ParsedInformeXml:
    metadata: dict[str, Any]
    scalar_df: pd.DataFrame
    list_df: pd.DataFrame


def parse_informe_mensal_xml(xml_content: bytes, doc_id: int) -> ParsedInformeXml:
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        raise DocumentParseError(f"XML inválido para documento {doc_id}: {exc}") from exc

    metadata = _extract_metadata(root)
    scalar_rows: list[dict[str, Any]] = []
    list_rows: list[dict[str, Any]] = []
    order_counter = 0

    def walk(
        node: ET.Element,
        normalized_path: list[str],
        display_path: list[str],
        repeated_contexts: list[dict[str, Any]],
    ) -> None:
        nonlocal order_counter
        children = list(node)
        if not children:
            value_raw = (node.text or "").strip()
            if not value_raw:
                return
            order_counter += 1
            tag_path = "/".join(normalized_path)
            field_path = "/".join(display_path)
            block, sub_block = _extract_block_parts(normalized_path)
            schema_match = resolve_schema_match(tag_path)
            value_num = _parse_numeric(value_raw)
            value_excel: Any = float(value_num) if value_num is not None else value_raw
            row = {
                "documento_id": doc_id,
                "competencia_xml": metadata.get("competencia_xml"),
                "xml_version": metadata.get("xml_version"),
                "bloco": block,
                "sub_bloco": sub_block,
                "tag": normalized_path[-1],
                "tag_path": tag_path,
                "field_path": field_path,
                "schema_path_match": schema_match.path,
                "schema_match_strategy": schema_match.strategy,
                "descricao": schema_match.description,
                "valor_raw": value_raw,
                "valor_num": float(value_num) if value_num is not None else pd.NA,
                "valor_excel": value_excel,
                "ordem_xml": order_counter,
            }
            if repeated_contexts:
                current_list = repeated_contexts[-1]
                list_rows.append(
                    {
                        **row,
                        "list_group_path": current_list["list_group_path"],
                        "list_item_path": current_list["list_item_path"],
                        "list_item_tag": current_list["list_item_tag"],
                        "list_index": current_list["list_index"],
                    }
                )
            else:
                scalar_rows.append(row)
            return

        counts = Counter(_strip_ns(child.tag) for child in children)
        # A LISTA_XXX container holds homogeneous XXX items — e.g.,
        # LISTA_CEDENT_CRED_EXISTE contains CEDENT_CRED_EXISTE entries.
        # When only one such item exists the sibling-count heuristic (> 1)
        # fails to detect the list context.  We detect it by name: if the
        # parent is LISTA_XXX and a child is named XXX it is always a list
        # item regardless of count.
        # NOTE: LISTA_INFORM breaks the XXX/LISTA_XXX pattern (its children
        # are heterogeneous sections such as APLIC_ATIVO and CART_SEGMT), so
        # the name check naturally excludes it.
        parent_tag = normalized_path[-1] if normalized_path else ""
        _LISTA_PREFIX = "LISTA_"
        expected_list_child: str | None = (
            parent_tag[len(_LISTA_PREFIX):] if parent_tag.upper().startswith(_LISTA_PREFIX) else None
        )
        seen: Counter[str] = Counter()
        for child in children:
            tag = _strip_ns(child.tag)
            seen[tag] += 1
            child_normalized_path = normalized_path + [tag]
            is_list_item = counts[tag] > 1 or (
                expected_list_child is not None and tag.upper() == expected_list_child.upper()
            )
            child_display_tag = f"{tag}[{seen[tag]}]" if is_list_item else tag
            child_display_path = display_path + [child_display_tag]
            next_contexts = list(repeated_contexts)
            if is_list_item:
                next_contexts.append(
                    {
                        "list_group_path": "/".join(child_normalized_path),
                        "list_item_path": "/".join(child_display_path),
                        "list_item_tag": tag,
                        "list_index": seen[tag],
                    }
                )
            walk(child, child_normalized_path, child_display_path, next_contexts)

    walk(root, [_strip_ns(root.tag)], [_strip_ns(root.tag)], [])

    scalar_df = pd.DataFrame(scalar_rows, columns=SCALAR_COLUMNS)
    list_df = pd.DataFrame(list_rows, columns=LIST_COLUMNS)
    return ParsedInformeXml(metadata=metadata, scalar_df=scalar_df, list_df=list_df)


def _extract_metadata(root: ET.Element) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    metadata["xml_version"] = _find_text(root, "./CAB_INFORM/VERSAO")
    metadata["competencia_xml"] = _find_text(root, "./CAB_INFORM/DT_COMPT")
    metadata["cnpj_administrador"] = _find_text(root, "./CAB_INFORM/NR_CNPJ_ADM")
    metadata["cnpj_fundo_xml"] = _find_text(root, "./CAB_INFORM/NR_CNPJ_FUNDO")
    metadata["nome_classe"] = _find_text(root, "./CAB_INFORM/NM_CLASSE")
    metadata["cnpj_classe"] = _find_text(root, "./CAB_INFORM/NR_CNPJ_CLASSE")
    metadata["class_unica"] = _find_text(root, "./CAB_INFORM/CLASS_UNICA")
    metadata["tp_condominio"] = _find_text(root, "./CAB_INFORM/TP_CONDOMINIO")
    return metadata


def _find_text(root: ET.Element, path: str) -> str | None:
    node = root.find(path)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _extract_block_parts(tag_path_parts: list[str]) -> tuple[str, str]:
    if len(tag_path_parts) < 2:
        return tag_path_parts[-1], ""
    if tag_path_parts[1] == "CAB_INFORM":
        return "CAB_INFORM", "/".join(tag_path_parts[2:-1])
    if tag_path_parts[1] == "LISTA_INFORM":
        block = tag_path_parts[2] if len(tag_path_parts) > 2 else "LISTA_INFORM"
        return block, "/".join(tag_path_parts[3:-1])
    return tag_path_parts[1], "/".join(tag_path_parts[2:-1])


def _parse_numeric(value: str) -> Decimal | None:
    candidate = (value or "").strip()
    if not candidate or not NUMERIC_RE.fullmatch(candidate):
        return None

    normalized = candidate
    if "," in candidate and "." in candidate:
        if candidate.rfind(",") > candidate.rfind("."):
            normalized = candidate.replace(".", "").replace(",", ".")
        else:
            normalized = candidate.replace(",", "")
    elif "," in candidate:
        normalized = candidate.replace(",", ".")

    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
