from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib import error, request
import uuid


PORTFOLIO_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_cnpj(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def portfolio_name_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def portfolio_basket_signature(funds: Iterable["PortfolioFund"]) -> str:
    unique_cnpjs = sorted({_normalize_cnpj(getattr(fund, "cnpj", "")) for fund in funds if _normalize_cnpj(getattr(fund, "cnpj", ""))})
    return "|".join(unique_cnpjs)


@dataclass(frozen=True)
class PortfolioFund:
    cnpj: str
    display_name: str

    def __post_init__(self) -> None:
        normalized_cnpj = _normalize_cnpj(self.cnpj)
        if len(normalized_cnpj) != 14:
            raise ValueError("CNPJ de fundo inválido para carteira.")
        object.__setattr__(self, "cnpj", normalized_cnpj)
        object.__setattr__(self, "display_name", str(self.display_name or normalized_cnpj).strip() or normalized_cnpj)

    def to_dict(self) -> dict[str, str]:
        return {
            "cnpj": self.cnpj,
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PortfolioFund:
        return cls(
            cnpj=str(payload.get("cnpj") or ""),
            display_name=str(payload.get("display_name") or payload.get("nome") or payload.get("cnpj") or ""),
        )


@dataclass(frozen=True)
class PortfolioRecord:
    id: str
    name: str
    funds: tuple[PortfolioFund, ...]
    created_at: str
    updated_at: str
    notes: str = ""

    def __post_init__(self) -> None:
        cleaned_name = str(self.name or "").strip()
        if not cleaned_name:
            raise ValueError("Nome da carteira é obrigatório.")
        deduped: list[PortfolioFund] = []
        seen: set[str] = set()
        for fund in self.funds:
            if fund.cnpj in seen:
                continue
            seen.add(fund.cnpj)
            deduped.append(fund)
        if not deduped:
            raise ValueError("A carteira precisa conter ao menos um fundo.")
        if len(deduped) > 20:
            raise ValueError("A carteira pode conter no máximo 20 fundos.")
        object.__setattr__(self, "name", cleaned_name)
        object.__setattr__(self, "funds", tuple(deduped))
        object.__setattr__(self, "notes", str(self.notes or "").strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "funds": [fund.to_dict() for fund in self.funds],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PortfolioRecord:
        return cls(
            id=str(payload.get("id") or uuid.uuid4().hex),
            name=str(payload.get("name") or ""),
            funds=tuple(PortfolioFund.from_dict(item) for item in payload.get("funds") or []),
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            updated_at=str(payload.get("updated_at") or payload.get("created_at") or _utc_now_iso()),
            notes=str(payload.get("notes") or ""),
        )


@dataclass(frozen=True)
class PortfolioCollection:
    schema_version: int
    portfolios: tuple[PortfolioRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "portfolios": [portfolio.to_dict() for portfolio in self.portfolios],
        }

    @classmethod
    def empty(cls) -> PortfolioCollection:
        return cls(schema_version=PORTFOLIO_SCHEMA_VERSION, portfolios=())

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> PortfolioCollection:
        raw = payload or {}
        schema_version = int(raw.get("schema_version") or PORTFOLIO_SCHEMA_VERSION)
        portfolios = tuple(
            sorted(
                (PortfolioRecord.from_dict(item) for item in raw.get("portfolios") or []),
                key=lambda record: record.name.lower(),
            )
        )
        return cls(schema_version=schema_version, portfolios=portfolios)


@dataclass(frozen=True)
class PortfolioStoreConfig:
    backend: str
    repo: str | None = None
    branch: str = "main"
    path: str = "portfolios.json"
    token: str | None = None
    local_path: str | None = None
    api_base_url: str = "https://api.github.com"


class PortfolioStore:
    def load_collection(self) -> PortfolioCollection:
        raise NotImplementedError

    def list_portfolios(self) -> list[PortfolioRecord]:
        return list(self.load_collection().portfolios)

    def save_portfolio(self, portfolio: PortfolioRecord) -> PortfolioRecord:
        raise NotImplementedError

    def delete_portfolio(self, portfolio_id: str) -> None:
        raise NotImplementedError


class LocalPortfolioStore(PortfolioStore):
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_collection(self) -> PortfolioCollection:
        if not self.path.exists():
            return PortfolioCollection.empty()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return PortfolioCollection.from_dict(payload)

    def save_portfolio(self, portfolio: PortfolioRecord) -> PortfolioRecord:
        collection = self.load_collection()
        saved = _upsert_collection(collection, portfolio)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(saved[0].to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return saved[1]

    def delete_portfolio(self, portfolio_id: str) -> None:
        collection = self.load_collection()
        updated = PortfolioCollection(
            schema_version=collection.schema_version,
            portfolios=tuple(portfolio for portfolio in collection.portfolios if portfolio.id != portfolio_id),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(updated.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class GitHubPortfolioStore(PortfolioStore):
    def __init__(
        self,
        *,
        repo: str,
        branch: str,
        path: str,
        token: str,
        api_base_url: str = "https://api.github.com",
    ) -> None:
        self.repo = repo
        self.branch = branch
        self.path = path
        self.token = token
        self.api_base_url = api_base_url.rstrip("/")

    def load_collection(self) -> PortfolioCollection:
        payload, _ = self._fetch_file()
        return PortfolioCollection.from_dict(payload)

    def save_portfolio(self, portfolio: PortfolioRecord) -> PortfolioRecord:
        payload, sha = self._fetch_file()
        collection = PortfolioCollection.from_dict(payload)
        updated_collection, stored_portfolio = _upsert_collection(collection, portfolio)
        try:
            self._write_file(
                updated_collection.to_dict(),
                sha=sha,
                message=f"Update portfolio {stored_portfolio.name}",
            )
        except error.HTTPError as exc:
            if exc.code != 409:
                raise
            payload, sha = self._fetch_file()
            updated_collection, stored_portfolio = _upsert_collection(PortfolioCollection.from_dict(payload), portfolio)
            self._write_file(
                updated_collection.to_dict(),
                sha=sha,
                message=f"Update portfolio {stored_portfolio.name}",
            )
        return stored_portfolio

    def delete_portfolio(self, portfolio_id: str) -> None:
        payload, sha = self._fetch_file()
        collection = PortfolioCollection.from_dict(payload)
        updated_collection = PortfolioCollection(
            schema_version=collection.schema_version,
            portfolios=tuple(portfolio for portfolio in collection.portfolios if portfolio.id != portfolio_id),
        )
        try:
            self._write_file(updated_collection.to_dict(), sha=sha, message=f"Delete portfolio {portfolio_id}")
        except error.HTTPError as exc:
            if exc.code != 409:
                raise
            payload, sha = self._fetch_file()
            collection = PortfolioCollection.from_dict(payload)
            updated_collection = PortfolioCollection(
                schema_version=collection.schema_version,
                portfolios=tuple(portfolio for portfolio in collection.portfolios if portfolio.id != portfolio_id),
            )
            self._write_file(updated_collection.to_dict(), sha=sha, message=f"Delete portfolio {portfolio_id}")

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "fidc-dashboard/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _contents_url(self) -> str:
        return f"{self.api_base_url}/repos/{self.repo}/contents/{self.path}?ref={self.branch}"

    def _fetch_file(self) -> tuple[dict[str, Any], str | None]:
        req = request.Request(self._contents_url(), headers=self._headers())
        try:
            with request.urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code == 404:
                return PortfolioCollection.empty().to_dict(), None
            raise
        content = base64.b64decode(payload.get("content", "").encode("utf-8")).decode("utf-8") if payload.get("content") else "{}"
        return json.loads(content), payload.get("sha")

    def _write_file(self, payload: dict[str, Any], *, sha: str | None, message: str) -> None:
        body = {
            "message": message,
            "content": base64.b64encode(
                json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            ).decode("utf-8"),
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha
        data = json.dumps(body).encode("utf-8")
        req = request.Request(
            f"{self.api_base_url}/repos/{self.repo}/contents/{self.path}",
            headers={**self._headers(), "Content-Type": "application/json"},
            data=data,
            method="PUT",
        )
        with request.urlopen(req, timeout=20):
            return


def _upsert_collection(
    collection: PortfolioCollection,
    portfolio: PortfolioRecord,
) -> tuple[PortfolioCollection, PortfolioRecord]:
    now = _utc_now_iso()
    duplicate = next(
        (
            item
            for item in collection.portfolios
            if item.id != portfolio.id
            and portfolio_name_key(item.name) == portfolio_name_key(portfolio.name)
            and portfolio_basket_signature(item.funds) == portfolio_basket_signature(portfolio.funds)
        ),
        None,
    )
    if duplicate is not None:
        raise ValueError(
            f"Já existe uma seleção idêntica salva com este nome e a mesma cesta de fundos ({duplicate.id[:8]})."
        )
    existing = next((item for item in collection.portfolios if item.id == portfolio.id), None)
    stored = PortfolioRecord(
        id=portfolio.id or uuid.uuid4().hex,
        name=portfolio.name,
        funds=portfolio.funds,
        created_at=existing.created_at if existing else (portfolio.created_at or now),
        updated_at=now,
        notes=portfolio.notes,
    )
    portfolios = [item for item in collection.portfolios if item.id != stored.id]
    portfolios.append(stored)
    updated = PortfolioCollection(
        schema_version=PORTFOLIO_SCHEMA_VERSION,
        portfolios=tuple(sorted(portfolios, key=lambda record: record.name.lower())),
    )
    return updated, stored


def build_portfolio_store(config: PortfolioStoreConfig) -> PortfolioStore:
    if config.backend == "github":
        if not config.repo or not config.token:
            raise ValueError("Configuração GitHub incompleta para persistência de carteiras.")
        return GitHubPortfolioStore(
            repo=config.repo,
            branch=config.branch,
            path=config.path,
            token=config.token,
            api_base_url=config.api_base_url,
        )
    local_path = Path(config.local_path or ".cache/portfolios.local.json")
    return LocalPortfolioStore(local_path)


def resolve_portfolio_store_config(
    *,
    secrets_mapping: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
) -> PortfolioStoreConfig:
    secrets_mapping = secrets_mapping or {}
    environ = environ or dict(os.environ)

    repo = str(secrets_mapping.get("github_repo") or environ.get("FIDC_GITHUB_REPO") or "").strip()
    branch = str(secrets_mapping.get("github_branch") or environ.get("FIDC_GITHUB_BRANCH") or "main").strip() or "main"
    path = str(
        secrets_mapping.get("github_portfolios_path")
        or environ.get("FIDC_GITHUB_PORTFOLIOS_PATH")
        or "portfolios.json"
    ).strip() or "portfolios.json"
    token = str(secrets_mapping.get("github_token") or environ.get("FIDC_GITHUB_TOKEN") or "").strip()
    api_base_url = str(
        secrets_mapping.get("github_api_base_url")
        or environ.get("FIDC_GITHUB_API_BASE_URL")
        or "https://api.github.com"
    ).strip() or "https://api.github.com"
    local_path = str(
        secrets_mapping.get("local_portfolios_path")
        or environ.get("FIDC_LOCAL_PORTFOLIOS_PATH")
        or ".cache/portfolios.local.json"
    ).strip() or ".cache/portfolios.local.json"

    if repo and token:
        return PortfolioStoreConfig(
            backend="github",
            repo=repo,
            branch=branch,
            path=path,
            token=token,
            api_base_url=api_base_url,
            local_path=local_path,
        )
    return PortfolioStoreConfig(
        backend="local",
        local_path=local_path,
        branch=branch,
        path=path,
        repo=repo or None,
        token=token or None,
        api_base_url=api_base_url,
    )
