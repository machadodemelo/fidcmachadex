from __future__ import annotations

import base64
from collections.abc import Iterable
from http.cookiejar import CookieJar
import html as html_lib
import json
import random
import re
import socket
import time
from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from services.fundonet_errors import AuthenticationRequiredError, ProviderUnavailableError
from services.fundonet_models import DocumentoFundo, FundoResolution


BASE_URL = "https://fnet.bmfbovespa.com.br/fnet/publico"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
MAX_PAGE_SIZE = 200
IME_CATEGORIA_ID = "6"
IME_TIPO_ID = "40"
REGULAMENTO_CATEGORIA_ID = "5"
FIDC_TIPO_ID = "2"
FUNDO_ITEM_TAG_RE = re.compile(
    r"<(?P<tag>[a-z0-9:_-]+)\b[^>]*\bclass\s*=\s*(?P<quote>['\"])[^'\"]*\bfundoItemInicial\b[^'\"]*(?P=quote)[^>]*>",
    re.IGNORECASE,
)
CSRF_PATTERNS = (
    re.compile(
        r"(?:window\.)?csrf_token\s*=\s*(?P<quote>['\"])(?P<token>[^'\"]+)(?P=quote)",
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name\s*=\s*(?P<quote>["\'])_csrf(?P=quote)[^>]+content\s*=\s*(?P<quote2>["\'])(?P<token>[^"\']+)(?P=quote2)',
        re.IGNORECASE,
    ),
    re.compile(
        r'<input[^>]+name\s*=\s*(?P<quote>["\'])_csrf(?P=quote)[^>]+value\s*=\s*(?P<quote2>["\'])(?P<token>[^"\']+)(?P=quote2)',
        re.IGNORECASE,
    ),
)


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


class FundosNetClient:
    def __init__(
        self,
        timeout_seconds: int = 30,
        max_retries: int = 2,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.csrf_token: Optional[str] = None
        self.referer_url: Optional[str] = None

    def resolve_fundo(self, cnpj_fundo: str) -> FundoResolution:
        cnpj = only_digits(cnpj_fundo)
        html = self._get_text(
            "abrirGerenciadorDocumentosCVM",
            params={"cnpjFundo": cnpj},
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            error_stage="abrir_gerenciador",
        )
        self.csrf_token = _extract_optional_csrf_token(html)
        self.referer_url = self._url("abrirGerenciadorDocumentosCVM", params={"cnpjFundo": cnpj})
        return _extract_fundo_resolution(cnpj=cnpj, html=html)

    def listar_documentos(
        self,
        cnpj_fundo: str,
        *,
        tipo_fundo: str = FIDC_TIPO_ID,
        categoria_id: str | None = None,
        tipo_id: str | None = None,
        especie_id: str | None = None,
        search_text: str = "",
        page_size: int = MAX_PAGE_SIZE,
        error_stage: str = "listar_documentos",
    ) -> list[DocumentoFundo]:
        cnpj = only_digits(cnpj_fundo)
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        start = 0
        draw = 1
        total = None
        documentos: list[DocumentoFundo] = []

        while total is None or start < total:
            params = [
                ("d", str(draw)),
                ("s", str(start)),
                ("l", str(page_size)),
                ("q", search_text or ""),
                ("cnpjFundo", cnpj),
                ("tipoFundo", tipo_fundo),
                ("idCategoriaDocumento", categoria_id),
                ("idTipoDocumento", tipo_id),
                ("idEspecieDocumento", especie_id),
                ("o[0][dataReferencia]", "asc"),
                ("o[1][dataEntrega]", "asc"),
            ]
            payload = self._get_json(
                "pesquisarGerenciadorDocumentosDados",
                params=params,
                accept="application/json, text/javascript, */*; q=0.01",
                error_stage=error_stage,
            )
            if payload.get("msg"):
                raise ProviderUnavailableError(
                    f"Listagem rejeitada pelo provedor: {payload.get('msg')}",
                    details={
                        "etapa": "listar_documentos",
                        "endpoint": "pesquisarGerenciadorDocumentosDados",
                        "msg": payload.get("msg"),
                        "draw": draw,
                        "start": start,
                    },
                )

            total = int(payload.get("recordsFiltered") or payload.get("recordsTotal") or 0)
            data = payload.get("data") or []
            if not data:
                break

            for item in data:
                doc_id = _safe_int(item.get("id"))
                if doc_id is None:
                    continue
                documentos.append(
                    DocumentoFundo(
                        id=doc_id,
                        categoria=str(item.get("categoriaDocumento", "") or ""),
                        tipo=str(item.get("tipoDocumento", "") or ""),
                        especie=str(item.get("especieDocumento", "") or ""),
                        data_referencia=_first_present(item, ["dataReferencia", "dtReferencia"]),
                        data_entrega=_first_present(item, ["dataEntrega", "dtEntrega"]),
                        nome_fundo=_first_present(item, ["descricaoFundo", "nomeFundo"]),
                        nome_arquivo=_first_present(item, ["nomeArquivo", "nmArquivo"]),
                        versao=_safe_int(item.get("versao"), default=0) or 0,
                        status=str(item.get("status", "") or ""),
                        fundo_ou_classe=_first_present(item, ["fundoOuClasse"]),
                        nome_administrador=_first_present(
                            item,
                            [
                                "nomeAdministrador",
                                "administrador",
                                "descricaoAdministrador",
                                "nomeAdm",
                                "descricaoAdm",
                                "razaoSocialAdministrador",
                                "denominacaoAdministrador",
                            ],
                        ),
                        nome_custodiante=_first_present(
                            item,
                            [
                                "nomeCustodiante",
                                "custodiante",
                                "descricaoCustodiante",
                                "nomeCustodia",
                                "descricaoCustodia",
                                "razaoSocialCustodiante",
                                "denominacaoCustodiante",
                            ],
                        ),
                        nome_gestor=_first_present(
                            item,
                            [
                                "nomeGestor",
                                "gestor",
                                "gestora",
                                "descricaoGestor",
                                "descricaoGestora",
                                "razaoSocialGestor",
                                "denominacaoGestor",
                            ],
                        ),
                        raw=item,
                    )
                )

            start += page_size
            draw += 1
            if start >= total:
                break

        return documentos

    def listar_documentos_ime(
        self,
        cnpj_fundo: str,
        *,
        page_size: int = MAX_PAGE_SIZE,
        fast_fail: bool = False,
    ) -> list[DocumentoFundo]:
        return self.listar_documentos(
            cnpj_fundo,
            categoria_id=IME_CATEGORIA_ID,
            tipo_id=IME_TIPO_ID,
            page_size=page_size,
            error_stage="listar_documentos_fast" if fast_fail else "listar_documentos",
        )

    def download_documento(self, doc_id: int) -> bytes:
        raw = self._get_bytes(
            "downloadDocumento",
            params={"id": str(doc_id)},
            accept="text/xml,application/xml,text/plain,*/*",
            error_stage="download_documento",
        )
        try:
            return _decode_download_payload(raw)
        except ValueError as exc:
            raise ProviderUnavailableError(
                f"Payload inesperado no download do documento {doc_id}.",
                details={
                    "etapa": "download_documento",
                    "endpoint": "downloadDocumento",
                    "documento_id": doc_id,
                },
            ) from exc

    def _get_text(
        self,
        path: str,
        *,
        params: dict[str, Any] | Iterable[tuple[str, str]] | None = None,
        accept: str,
        error_stage: str,
    ) -> str:
        return self._get_bytes(path, params=params, accept=accept, error_stage=error_stage).decode(
            "utf-8", errors="replace"
        )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | Iterable[tuple[str, str]] | None = None,
        accept: str,
        error_stage: str,
    ) -> dict[str, Any]:
        raw = self._get_bytes(path, params=params, accept=accept, error_stage=error_stage)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderUnavailableError(
                "Resposta JSON inválida do provedor.",
                details={
                    "etapa": error_stage,
                    "endpoint": path,
                },
            ) from exc

    def _get_bytes(
        self,
        path: str,
        *,
        params: dict[str, Any] | Iterable[tuple[str, str]] | None = None,
        accept: str,
        error_stage: str,
    ) -> bytes:
        url = self._url(path, params=params)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
        }
        if self.referer_url:
            headers["Referer"] = self.referer_url
        if self.csrf_token:
            headers["CSRFToken"] = self.csrf_token

        last_error: Exception | None = None
        retry_limit = self._retry_limit_for_stage(error_stage)
        timeout_seconds = self._timeout_for_stage(error_stage)
        for attempt in range(retry_limit + 1):
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with self.opener.open(request, timeout=timeout_seconds) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                body = exc.read() if exc.fp else b""
                if exc.code == 403:
                    raise AuthenticationRequiredError(
                        f"Requisição bloqueada pelo provedor (HTTP 403) em {path}.",
                        details={
                            "etapa": error_stage,
                            "endpoint": path,
                            "http_status": exc.code,
                            "url": url,
                            "body_prefix": body[:200].decode("utf-8", errors="replace"),
                            "tentativas": attempt + 1,
                            "timeout_seconds": timeout_seconds,
                        },
                    ) from exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < retry_limit:
                    time.sleep(self._retry_sleep_seconds(attempt, error_stage))
                    continue
                raise ProviderUnavailableError(
                    f"Fundos.NET respondeu HTTP {exc.code} em {path}.",
                    details={
                        "etapa": error_stage,
                        "endpoint": path,
                        "http_status": exc.code,
                        "url": url,
                        "body_prefix": body[:200].decode("utf-8", errors="replace"),
                        "tentativas": attempt + 1,
                        "timeout_seconds": timeout_seconds,
                    },
                ) from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                last_error = exc
                if attempt < retry_limit:
                    time.sleep(self._retry_sleep_seconds(attempt, error_stage))
                    continue
                break

        raise ProviderUnavailableError(
            f"Falha de rede ao acessar {path}: {last_error}",
            details={
                "etapa": error_stage,
                "endpoint": path,
                "url": url,
                "tentativas": retry_limit + 1,
                "timeout_seconds": timeout_seconds,
            },
        )

    def _timeout_for_stage(self, error_stage: str) -> int:
        if error_stage == "listar_documentos_fast":
            return min(max(self.timeout_seconds, 12), 20)
        if error_stage in {"abrir_gerenciador", "listar_documentos"}:
            return max(self.timeout_seconds, 45)
        if error_stage == "download_documento":
            return max(self.timeout_seconds, 40)
        return self.timeout_seconds

    def _retry_limit_for_stage(self, error_stage: str) -> int:
        if error_stage == "listar_documentos_fast":
            return 1
        if error_stage in {"abrir_gerenciador", "listar_documentos"}:
            return max(self.max_retries, 3)
        return self.max_retries

    def _retry_sleep_seconds(self, attempt: int, error_stage: str) -> float:
        base = 1.1 if error_stage in {"abrir_gerenciador", "listar_documentos", "listar_documentos_fast"} else 0.7
        return base * (2**attempt) + random.uniform(0.0, 0.45)

    def _url(
        self,
        path: str,
        params: dict[str, Any] | Iterable[tuple[str, str]] | None = None,
    ) -> str:
        base = f"{BASE_URL}/{path.lstrip('/')}"
        if not params:
            return base
        # Use quote (not quote_plus) with safe='[]' so DataTables bracket params
        # like o[0][campo]=asc reach the server unencoded, as the backend expects.
        query = urllib.parse.urlencode(
            list(_iter_params(params)),
            doseq=True,
            quote_via=urllib.parse.quote,
            safe="[]",
        )
        return f"{base}?{query}"


def _iter_params(
    params: dict[str, Any] | Iterable[tuple[str, str]],
) -> Iterable[tuple[str, str]]:
    if isinstance(params, dict):
        for key, value in params.items():
            if value in (None, ""):
                continue
            yield str(key), str(value)
        return
    for key, value in params:
        if value in (None, ""):
            continue
        yield str(key), str(value)


def _decode_download_payload(raw: bytes) -> bytes:
    if raw.lstrip().startswith((b"<?xml", b"%PDF", b"PK\x03\x04")):
        return raw
    stripped = raw.decode("utf-8", errors="replace").strip()
    if stripped.startswith("<?xml"):
        return stripped.encode("utf-8")
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("download payload is not valid base64") from exc
    if not decoded:
        raise ValueError("decoded payload is empty")
    return decoded


def _extract_fundo_resolution(cnpj: str, html: str) -> FundoResolution:
    for match in FUNDO_ITEM_TAG_RE.finditer(html):
        tag = match.group(0)
        id_fundo = _extract_html_attr(tag, "data-id")
        nome_fundo = _extract_html_attr(tag, "data-text")
        if id_fundo:
            return FundoResolution(
                cnpj=cnpj,
                id_fundo=id_fundo,
                nome_fundo=nome_fundo,
            )
    return FundoResolution(cnpj=cnpj, id_fundo=None, nome_fundo=None)


def _extract_optional_csrf_token(html: str) -> Optional[str]:
    for pattern in CSRF_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group("token")
    return None


def _extract_html_attr(tag: str, attr_name: str) -> Optional[str]:
    pattern = re.compile(
        rf"""\b{re.escape(attr_name)}\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)')""",
        re.IGNORECASE,
    )
    match = pattern.search(tag)
    if not match:
        return None
    value = match.group("double") or match.group("single") or ""
    return html_lib.unescape(value)


def _first_present(item: dict[str, Any], candidates: list[str]) -> Optional[str]:
    for key in candidates:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
