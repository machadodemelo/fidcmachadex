from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_CONFIG: dict[str, Any] = {
    "repositorios": ["abalroar/fidc"],
    "limiar_sessao_min": 90,
    "overhead_sessao_min": 20,
    "incluir_merges": False,
    "incluir_prs": True,
}

CONFIG_PATH = Path("data/dev_hours_config.json")
CACHE_PATH = Path("data/dev_hours_cache.json")
CACHE_TTL_HOURS = 24
GITHUB_API_BASE = "https://api.github.com"


class DevHoursError(RuntimeError):
    """Base error for development-hours estimation."""


class GitHubFetchError(DevHoursError):
    def __init__(self, status_code: int, message: str, *, repo: str | None = None) -> None:
        self.status_code = status_code
        self.repo = repo
        super().__init__(message)


@dataclass(frozen=True)
class CommitRecord:
    sha: str
    timestamp: datetime
    message: str
    repo: str


@dataclass(frozen=True)
class PullRequestRecord:
    number: int
    title: str
    state: str
    created_at: str | None
    merged_at: str | None
    closed_at: str | None
    author: str
    repo: str


@dataclass(frozen=True)
class WorkSession:
    start: datetime
    end: datetime
    commits: int
    base_hours: float
    overhead_hours: float
    repo_count: int


Transport = Callable[[str, dict[str, str]], tuple[int, Any]]


class GitHubApiClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        api_base_url: str = GITHUB_API_BASE,
        transport: Transport | None = None,
    ) -> None:
        self.token = token.strip() if token else None
        self.api_base_url = api_base_url.rstrip("/")
        self.transport = transport or _urllib_transport
        self.used_unauthenticated_fallback = False
        self.token_invalid = False

    def get_json(self, path: str, *, params: dict[str, Any] | None = None, repo: str | None = None) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.api_base_url}{path}{query}"
        if self.token:
            try:
                return self._request(url, authorized=True, repo=repo)
            except GitHubFetchError as exc:
                if exc.status_code != 401:
                    raise
                self.token_invalid = True
                self.used_unauthenticated_fallback = True
        return self._request(url, authorized=False, repo=repo)

    def _request(self, url: str, *, authorized: bool, repo: str | None) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "tomaconta-dev-hours",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if authorized and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        status_code, payload = self.transport(url, headers)
        if status_code >= 400:
            raise GitHubFetchError(status_code, _github_error_message(status_code, payload, repo=repo), repo=repo)
        return payload


def load_dev_hours_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)
    config = dict(DEFAULT_CONFIG)
    config.update({key: value for key, value in payload.items() if value is not None})
    config["repositorios"] = _normalize_repositories(config.get("repositorios"))
    config["limiar_sessao_min"] = int(config.get("limiar_sessao_min") or DEFAULT_CONFIG["limiar_sessao_min"])
    config["overhead_sessao_min"] = int(config.get("overhead_sessao_min") or DEFAULT_CONFIG["overhead_sessao_min"])
    config["incluir_merges"] = bool(config.get("incluir_merges"))
    config["incluir_prs"] = bool(config.get("incluir_prs"))
    return config


def save_dev_hours_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(config)
    normalized["repositorios"] = _normalize_repositories(normalized.get("repositorios"))
    normalized["limiar_sessao_min"] = int(normalized.get("limiar_sessao_min") or DEFAULT_CONFIG["limiar_sessao_min"])
    normalized["overhead_sessao_min"] = int(normalized.get("overhead_sessao_min") or DEFAULT_CONFIG["overhead_sessao_min"])
    normalized["incluir_merges"] = bool(normalized.get("incluir_merges"))
    normalized["incluir_prs"] = bool(normalized.get("incluir_prs"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return normalized


def invalidate_dev_hours_cache(path: Path = CACHE_PATH) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def read_github_token(*, secrets_mapping: dict[str, Any] | None = None, environ: dict[str, str] | None = None) -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        value = None
        if secrets_mapping:
            value = secrets_mapping.get(key) or secrets_mapping.get(key.lower())
        if value:
            return str(value).strip()
    env = environ if environ is not None else os.environ
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        value = env.get(key)
        if value:
            return value.strip()
    return None


def build_development_investment(
    config: dict[str, Any],
    *,
    token: str | None = None,
    client: GitHubApiClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_now = now or datetime.now(timezone.utc)
    repos = _normalize_repositories(config.get("repositorios"))
    resolved_config = dict(DEFAULT_CONFIG)
    resolved_config.update(config)
    resolved_config["repositorios"] = repos
    client = client or GitHubApiClient(token=token)

    commits: list[CommitRecord] = []
    prs: list[PullRequestRecord] = []
    warnings: list[str] = []
    for repo in repos:
        try:
            commits.extend(fetch_commits_for_repo(client, repo, incluir_merges=bool(resolved_config.get("incluir_merges"))))
            if resolved_config.get("incluir_prs"):
                prs.extend(fetch_pull_requests_for_repo(client, repo))
        except GitHubFetchError as exc:
            warnings.append(str(exc))

    if repos and not commits and warnings:
        raise DevHoursError("; ".join(warnings))

    deduped_commits = deduplicate_commits(commits)
    sessions = build_work_sessions(
        deduped_commits,
        limiar_sessao_min=int(resolved_config["limiar_sessao_min"]),
        overhead_sessao_min=int(resolved_config["overhead_sessao_min"]),
    )
    summary = summarize_development_activity(
        commits=deduped_commits,
        prs=prs,
        sessions=sessions,
        config=resolved_config,
        generated_at=resolved_now,
        warnings=warnings,
    )
    if client.token_invalid:
        summary["warnings"].append("Token GitHub inválido ou expirado; consulta refeita sem autenticação.")
    return summary


def get_development_investment(
    config: dict[str, Any],
    *,
    token: str | None = None,
    cache_path: Path = CACHE_PATH,
    refresh: bool = False,
    now: datetime | None = None,
    client: GitHubApiClient | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    resolved_now = now or datetime.now(timezone.utc)
    signature = config_signature(config)
    cached = _read_cache(cache_path)
    if not refresh and cached and is_cache_valid(cached, signature=signature, now=resolved_now):
        return dict(cached["payload"]), "cache", []
    try:
        payload = build_development_investment(config, token=token, client=client, now=resolved_now)
        _write_cache(cache_path, signature=signature, payload=payload, generated_at=resolved_now)
        return payload, "github", []
    except Exception as exc:  # noqa: BLE001
        if cached and "payload" in cached:
            warning = f"Atualização falhou; exibindo cache antigo. Motivo: {exc}"
            payload = dict(cached["payload"])
            payload.setdefault("warnings", []).append(warning)
            return payload, "cache_stale", [warning]
        raise


def load_cached_development_investment(
    config: dict[str, Any],
    *,
    cache_path: Path = CACHE_PATH,
    now: datetime | None = None,
    allow_stale: bool = True,
) -> tuple[dict[str, Any], str] | tuple[None, str]:
    signature = config_signature(config)
    cached = _read_cache(cache_path)
    if not cached or "payload" not in cached:
        return None, "miss"
    if cached.get("config_signature") != signature:
        return None, "miss"
    if is_cache_valid(cached, signature=signature, now=now):
        return dict(cached["payload"]), "cache"
    if allow_stale:
        payload = dict(cached["payload"])
        payload.setdefault("warnings", []).append("Cache local está fora do TTL de 24h; clique em Recalcular estimativa para atualizar.")
        return payload, "cache_stale"
    return None, "miss"


def is_cache_valid(cache_payload: dict[str, Any], *, signature: str, now: datetime | None = None, ttl_hours: int = CACHE_TTL_HOURS) -> bool:
    if cache_payload.get("config_signature") != signature:
        return False
    generated_at = _parse_datetime(cache_payload.get("generated_at"))
    if generated_at is None:
        return False
    resolved_now = now or datetime.now(timezone.utc)
    return resolved_now - generated_at <= timedelta(hours=ttl_hours)


def fetch_commits_for_repo(client: GitHubApiClient, repo: str, *, incluir_merges: bool) -> list[CommitRecord]:
    owner, name = _split_repo(repo)
    records: list[CommitRecord] = []
    page = 1
    while True:
        payload = client.get_json(
            f"/repos/{owner}/{name}/commits",
            params={"per_page": 100, "page": page},
            repo=repo,
        )
        if not payload:
            break
        if not isinstance(payload, list):
            raise GitHubFetchError(502, f"Resposta inesperada ao buscar commits de {repo}.", repo=repo)
        for item in payload:
            parents = item.get("parents") or []
            message = str(((item.get("commit") or {}).get("message")) or "")
            if not incluir_merges and (len(parents) > 1 or message.lower().startswith("merge ")):
                continue
            raw_date = ((item.get("commit") or {}).get("author") or {}).get("date")
            timestamp = _parse_datetime(raw_date)
            sha = str(item.get("sha") or "").strip()
            if not timestamp or not sha:
                continue
            records.append(CommitRecord(sha=sha, timestamp=timestamp, message=message, repo=repo))
        if len(payload) < 100:
            break
        page += 1
    return records


def fetch_pull_requests_for_repo(client: GitHubApiClient, repo: str) -> list[PullRequestRecord]:
    owner, name = _split_repo(repo)
    records: list[PullRequestRecord] = []
    page = 1
    while True:
        payload = client.get_json(
            f"/repos/{owner}/{name}/pulls",
            params={"state": "all", "per_page": 100, "page": page},
            repo=repo,
        )
        if not payload:
            break
        if not isinstance(payload, list):
            raise GitHubFetchError(502, f"Resposta inesperada ao buscar PRs de {repo}.", repo=repo)
        for item in payload:
            user = item.get("user") or {}
            records.append(
                PullRequestRecord(
                    number=int(item.get("number") or 0),
                    title=str(item.get("title") or ""),
                    state=str(item.get("state") or ""),
                    created_at=item.get("created_at"),
                    merged_at=item.get("merged_at"),
                    closed_at=item.get("closed_at"),
                    author=str(user.get("login") or ""),
                    repo=repo,
                )
            )
        if len(payload) < 100:
            break
        page += 1
    return records


def deduplicate_commits(commits: list[CommitRecord]) -> list[CommitRecord]:
    by_sha: dict[str, CommitRecord] = {}
    for commit in commits:
        by_sha.setdefault(commit.sha, commit)
    by_fingerprint: dict[tuple[int, str], CommitRecord] = {}
    for commit in sorted(by_sha.values(), key=lambda item: item.timestamp):
        fingerprint = (int(commit.timestamp.timestamp()), _normalize_message(commit.message))
        by_fingerprint.setdefault(fingerprint, commit)
    return sorted(by_fingerprint.values(), key=lambda item: item.timestamp)


def build_work_sessions(
    commits: list[CommitRecord],
    *,
    limiar_sessao_min: int,
    overhead_sessao_min: int,
) -> list[WorkSession]:
    ordered = sorted(commits, key=lambda item: item.timestamp)
    if not ordered:
        return []
    threshold = timedelta(minutes=limiar_sessao_min)
    grouped: list[list[CommitRecord]] = [[ordered[0]]]
    for commit in ordered[1:]:
        gap = commit.timestamp - grouped[-1][-1].timestamp
        if gap > threshold:
            grouped.append([commit])
        else:
            grouped[-1].append(commit)
    overhead_hours = overhead_sessao_min / 60.0
    sessions: list[WorkSession] = []
    for group in grouped:
        start = group[0].timestamp
        end = group[-1].timestamp
        base_hours = max((end - start).total_seconds() / 3600.0, 0.0)
        sessions.append(
            WorkSession(
                start=start,
                end=end,
                commits=len(group),
                base_hours=base_hours,
                overhead_hours=overhead_hours,
                repo_count=len({commit.repo for commit in group}),
            )
        )
    return sessions


def summarize_development_activity(
    *,
    commits: list[CommitRecord],
    prs: list[PullRequestRecord],
    sessions: list[WorkSession],
    config: dict[str, Any],
    generated_at: datetime,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    base_hours = sum(session.base_hours for session in sessions)
    overhead_hours = sum(session.overhead_hours for session in sessions)
    total_hours = base_hours + overhead_hours
    merged_prs = sum(1 for pr in prs if pr.merged_at)
    first_commit = min((commit.timestamp for commit in commits), default=None)
    last_commit = max((commit.timestamp for commit in commits), default=None)
    weekly = build_weekly_breakdown(sessions)
    session_durations = [
        {
            "inicio": session.start.isoformat(),
            "fim": session.end.isoformat(),
            "commits": session.commits,
            "horas_base": round(session.base_hours, 4),
            "overhead_horas": round(session.overhead_hours, 4),
            "total_horas": round(session.base_hours + session.overhead_hours, 4),
        }
        for session in sessions
    ]
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "config": config,
        "repositorios": config.get("repositorios", []),
        "total_commits": len(commits),
        "total_prs": len(prs),
        "prs_mergeados": merged_prs,
        "sessoes_trabalho": len(sessions),
        "horas_base_commits": round(base_hours, 4),
        "horas_overhead": round(overhead_hours, 4),
        "total_horas": round(total_hours, 4),
        "estimativa_min_horas": round(base_hours, 4),
        "estimativa_central_horas": round(total_hours, 4),
        "estimativa_max_horas": round(base_hours + len(sessions), 4),
        "sessao_media_horas": round(total_hours / len(sessions), 4) if sessions else 0.0,
        "primeiro_commit": first_commit.isoformat() if first_commit else None,
        "ultimo_commit": last_commit.isoformat() if last_commit else None,
        "commits_por_mes": build_commits_by_month(commits),
        "sessoes": session_durations,
        "weekly_breakdown": weekly,
        "warnings": list(warnings or []),
    }


def build_commits_by_month(commits: list[CommitRecord]) -> list[dict[str, Any]]:
    grouped: dict[str, int] = {}
    for commit in commits:
        key = commit.timestamp.strftime("%Y-%m")
        grouped[key] = grouped.get(key, 0) + 1
    return [{"mes": key, "commits": grouped[key]} for key in sorted(grouped)]


def build_weekly_breakdown(sessions: list[WorkSession]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = {}
    for session in sessions:
        week_start = (session.start.date() - timedelta(days=session.start.weekday())).isoformat()
        bucket = grouped.setdefault(week_start, {"horas_base_commits": 0.0, "horas_overhead": 0.0, "sessoes": 0.0})
        bucket["horas_base_commits"] += session.base_hours
        bucket["horas_overhead"] += session.overhead_hours
        bucket["sessoes"] += 1
    output = []
    for week_start in sorted(grouped):
        item = grouped[week_start]
        output.append(
            {
                "semana_inicio": week_start,
                "horas_base_commits": round(item["horas_base_commits"], 4),
                "horas_overhead": round(item["horas_overhead"], 4),
                "total_horas": round(item["horas_base_commits"] + item["horas_overhead"], 4),
                "sessoes": int(item["sessoes"]),
            }
        )
    return output


def config_signature(config: dict[str, Any]) -> str:
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(config)
    normalized["repositorios"] = _normalize_repositories(normalized.get("repositorios"))
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(path: Path, *, signature: str, payload: dict[str, Any], generated_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "config_signature": signature,
        "payload": payload,
    }
    path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _urllib_transport(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            status = int(getattr(response, "status", 200))
            raw_payload = response.read().decode("utf-8")
            return status, json.loads(raw_payload) if raw_payload else None
    except HTTPError as exc:
        try:
            raw_payload = exc.read().decode("utf-8")
            payload = json.loads(raw_payload) if raw_payload else {}
        except Exception:  # noqa: BLE001
            payload = {"message": str(exc)}
        return int(exc.code), payload
    except URLError as exc:
        raise DevHoursError(f"Falha de rede ao consultar GitHub: {exc.reason}") from exc


def _github_error_message(status_code: int, payload: Any, *, repo: str | None) -> str:
    api_message = ""
    if isinstance(payload, dict):
        api_message = str(payload.get("message") or "")
    suffix = f" ({repo})" if repo else ""
    normalized = api_message.lower()
    if status_code == 401:
        return f"Token GitHub inválido ou autenticação recusada{suffix}."
    if status_code == 403 and "rate limit" in normalized:
        return f"Rate limit do GitHub atingido{suffix}."
    if status_code == 403:
        return f"Repositório sem acesso ou bloqueado pelo GitHub{suffix}."
    if status_code == 404:
        return f"Repositório inexistente ou sem acesso{suffix}."
    return f"Erro GitHub {status_code}{suffix}: {api_message or 'sem detalhe'}."


def _normalize_repositories(repositories: Any) -> list[str]:
    if isinstance(repositories, str):
        raw_items = re.split(r"[\n,;]+", repositories)
    elif isinstance(repositories, list | tuple | set):
        raw_items = list(repositories)
    else:
        raw_items = list(DEFAULT_CONFIG["repositorios"])
    output = []
    seen = set()
    for item in raw_items:
        text = str(item or "").strip()
        if not text or "/" not in text:
            continue
        owner, repo = text.split("/", 1)
        normalized = f"{owner.strip()}/{repo.strip()}"
        key = normalized.lower()
        if normalized and key not in seen:
            output.append(normalized)
            seen.add(key)
    return output or list(DEFAULT_CONFIG["repositorios"])


def _split_repo(repo: str) -> tuple[str, str]:
    parts = str(repo or "").strip().split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise DevHoursError(f"Repositório inválido: {repo!r}. Use owner/repo.")
    return parts[0], parts[1]


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize_message(message: str) -> str:
    return re.sub(r"\s+", " ", str(message or "").strip().lower())
