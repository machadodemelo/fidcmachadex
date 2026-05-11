from __future__ import annotations

from dataclasses import dataclass
import json
import re
from functools import lru_cache
from pathlib import Path


SCHEMA_576_MAP_PATH = Path(__file__).with_name("fundonet_schema_576.json")
INDEX_SUFFIX_RE = re.compile(r"\[\d+\]")


@dataclass(frozen=True)
class SchemaMatch:
    path: str | None
    description: str | None
    strategy: str | None


def normalize_tag_path(tag_path: str) -> str:
    return INDEX_SUFFIX_RE.sub("", tag_path or "")


def resolve_schema_match(tag_path: str) -> SchemaMatch:
    normalized = normalize_tag_path(tag_path)
    mapping = _load_schema_mapping()

    exact = mapping.get(normalized)
    if exact:
        return SchemaMatch(path=normalized, description=_clean_description(exact), strategy="exact")

    parts = normalized.split("/")
    for suffix_len in range(min(5, len(parts)), 1, -1):
        suffix = "/".join(parts[-suffix_len:])
        matches = _schema_suffix_index().get(suffix, [])
        if len(matches) == 1:
            match_path = matches[0]
            return SchemaMatch(
                path=match_path,
                description=_clean_description(mapping[match_path]),
                strategy=f"suffix_{suffix_len}",
            )

    leaf = parts[-1] if parts else ""
    leaf_matches = _schema_leaf_index().get(leaf, [])
    if len(leaf_matches) == 1:
        match_path = leaf_matches[0]
        return SchemaMatch(
            path=match_path,
            description=_clean_description(mapping[match_path]),
            strategy="leaf_unique",
        )

    return SchemaMatch(path=None, description=None, strategy=None)


@lru_cache(maxsize=1)
def _load_schema_mapping() -> dict[str, str]:
    if not SCHEMA_576_MAP_PATH.exists():
        return {}
    with SCHEMA_576_MAP_PATH.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    return {str(key): str(value) for key, value in payload.items()}


@lru_cache(maxsize=1)
def _schema_suffix_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for path in _load_schema_mapping():
        parts = path.split("/")
        for suffix_len in range(2, min(5, len(parts)) + 1):
            suffix = "/".join(parts[-suffix_len:])
            index.setdefault(suffix, []).append(path)
    return index


@lru_cache(maxsize=1)
def _schema_leaf_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for path in _load_schema_mapping():
        leaf = path.split("/")[-1]
        index.setdefault(leaf, []).append(path)
    return index


def _clean_description(description: str) -> str:
    cleaned = (description or "").strip()
    for prefix in (
        "SUBSTITUA ESTA FRASE PELO ",
        "SUBSTITUA ESTA FRASE COM O ",
        "SUBSTITUA ESTA FRASE COM A ",
        "SUBSTITUA ESTA FRASE COM ",
        "SUBSTITUA ESTA FRASE PELA ",
    ):
        if cleaned.upper().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned.rstrip(".")
