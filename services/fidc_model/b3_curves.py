"""Public B3 TaxaSwap curve loader used by the Modelo FIDC simulation.

The B3 site exposes the daily file as TS{YYMMDD}.ex_ through Pesquisa por Pregão.
The downloaded ZIP wraps a self-extracting archive that contains TaxaSwap.txt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from typing import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


B3_TAXASWAP_DOWNLOAD_URL = "https://www.b3.com.br/pesquisapregao/download?filelist={filename},"
DEFAULT_TAXASWAP_CURVE_CODE = "PRE"
DEFAULT_TAXASWAP_LOOKBACK_DAYS = 20
TAXASWAP_RECORD_WIDTH = 72


class B3CurveError(RuntimeError):
    """Raised when the B3 curve cannot be fetched or parsed without ambiguity."""


@dataclass(frozen=True)
class B3CurvePoint:
    dc: int
    du: int
    rate_aa: float
    description: str
    vertex_kind: str
    vertex_code: str


@dataclass(frozen=True)
class B3CurveSnapshot:
    curve_code: str
    generated_at: date
    requested_date: date | None
    retrieved_at: datetime
    source_url: str
    content_sha256: str
    points: tuple[B3CurvePoint, ...]
    raw_line_count: int

    @property
    def curva_du(self) -> list[float]:
        return [float(point.du) for point in self.points]

    @property
    def curva_taxa_aa(self) -> list[float]:
        return [float(point.rate_aa) for point in self.points]

    @property
    def first_du(self) -> int | None:
        return self.points[0].du if self.points else None

    @property
    def last_du(self) -> int | None:
        return self.points[-1].du if self.points else None


def taxaswap_filename(base_date: date) -> str:
    return f"TS{base_date:%y%m%d}.ex_"


def taxaswap_download_url(base_date: date) -> str:
    return B3_TAXASWAP_DOWNLOAD_URL.format(filename=taxaswap_filename(base_date))


def parse_taxaswap_archive(
    payload: bytes,
    *,
    curve_code: str = DEFAULT_TAXASWAP_CURVE_CODE,
    requested_date: date | None = None,
    source_url: str = "",
    retrieved_at: datetime | None = None,
) -> B3CurveSnapshot:
    text = _extract_taxaswap_text(payload)
    return parse_taxaswap_text(
        text,
        curve_code=curve_code,
        requested_date=requested_date,
        source_url=source_url,
        retrieved_at=retrieved_at,
        content_hash=sha256(payload).hexdigest(),
    )


def parse_taxaswap_text(
    text: str,
    *,
    curve_code: str = DEFAULT_TAXASWAP_CURVE_CODE,
    requested_date: date | None = None,
    source_url: str = "",
    retrieved_at: datetime | None = None,
    content_hash: str = "",
) -> B3CurveSnapshot:
    target_code = curve_code.strip().upper()
    parsed_points: list[B3CurvePoint] = []
    generated_dates: set[date] = set()
    raw_lines = [line.rstrip("\r\n") for line in text.splitlines() if line.strip()]

    for line in raw_lines:
        if len(line) < TAXASWAP_RECORD_WIDTH:
            continue
        fields = _parse_taxaswap_line(line)
        if fields["cod_taxa"].upper() != target_code:
            continue
        generated_dates.add(_parse_yyyymmdd(fields["data_geracao_arquivo"]))
        parsed_points.append(
            B3CurvePoint(
                dc=int(fields["num_dias_corridos"]),
                du=int(fields["num_dias_saques"]),
                rate_aa=_parse_taxaswap_rate(fields["sinal_taxa"], fields["taxa_teorica"]),
                description=fields["desc"].strip(),
                vertex_kind=fields["carat_vertice"].strip(),
                vertex_code=fields["cod_vertice"].strip(),
            )
        )

    if not parsed_points:
        raise B3CurveError(f"Arquivo TaxaSwap não contém pontos para a curva {target_code}.")
    if len(generated_dates) != 1:
        raise B3CurveError("Arquivo TaxaSwap contém mais de uma data de geração para a curva selecionada.")

    generated_at = next(iter(generated_dates))
    if requested_date is not None and generated_at != requested_date:
        raise B3CurveError(
            f"Arquivo TaxaSwap gerado em {generated_at:%d/%m/%Y}, mas a data solicitada foi {requested_date:%d/%m/%Y}."
        )

    points = _dedupe_and_sort_points(parsed_points)
    _validate_points(points, target_code)
    return B3CurveSnapshot(
        curve_code=target_code,
        generated_at=generated_at,
        requested_date=requested_date,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        source_url=source_url,
        content_sha256=content_hash,
        points=tuple(points),
        raw_line_count=len(raw_lines),
    )


def fetch_taxaswap_curve(
    base_date: date,
    *,
    curve_code: str = DEFAULT_TAXASWAP_CURVE_CODE,
    timeout: float = 30.0,
    opener: Callable[..., object] | None = None,
) -> B3CurveSnapshot:
    url = taxaswap_download_url(base_date)
    request = Request(
        url,
        headers={
            "User-Agent": "fidc-streamlit-model/1.0",
            "Accept": "application/zip, application/octet-stream, */*",
        },
    )
    open_func = opener or urlopen
    try:
        with open_func(request, timeout=timeout) as response:  # type: ignore[misc]
            payload = response.read()
    except HTTPError as exc:
        raise B3CurveError(f"B3 retornou HTTP {exc.code} para {base_date:%d/%m/%Y}.") from exc
    except URLError as exc:
        raise B3CurveError(f"Falha de rede ao consultar B3 para {base_date:%d/%m/%Y}: {exc.reason}.") from exc
    except OSError as exc:
        raise B3CurveError(f"Falha ao consultar B3 para {base_date:%d/%m/%Y}: {exc}.") from exc

    if not payload:
        raise B3CurveError(f"B3 retornou arquivo vazio para {base_date:%d/%m/%Y}.")

    return parse_taxaswap_archive(
        payload,
        curve_code=curve_code,
        requested_date=base_date,
        source_url=url,
        retrieved_at=datetime.now(timezone.utc),
    )


def fetch_latest_taxaswap_curve(
    *,
    start_date: date | None = None,
    curve_code: str = DEFAULT_TAXASWAP_CURVE_CODE,
    lookback_days: int = DEFAULT_TAXASWAP_LOOKBACK_DAYS,
    timeout: float = 30.0,
    fetcher: Callable[..., B3CurveSnapshot] = fetch_taxaswap_curve,
) -> B3CurveSnapshot:
    first_date = start_date or datetime.now().date()
    errors: list[str] = []
    for offset in range(lookback_days + 1):
        candidate = first_date - timedelta(days=offset)
        try:
            return fetcher(candidate, curve_code=curve_code, timeout=timeout)
        except B3CurveError as exc:
            errors.append(f"{candidate:%d/%m/%Y}: {exc}")
    raise B3CurveError(
        "Não foi possível localizar uma curva TaxaSwap válida na B3 "
        f"entre {first_date - timedelta(days=lookback_days):%d/%m/%Y} e {first_date:%d/%m/%Y}. "
        f"Último erro: {errors[-1] if errors else 'sem detalhe'}"
    )


def _extract_taxaswap_text(payload: bytes) -> str:
    if not _looks_like_zip(payload):
        snippet = payload[:160].decode("latin-1", errors="replace").strip()
        raise B3CurveError(f"Resposta da B3 não é ZIP TaxaSwap. Início da resposta: {snippet!r}")

    try:
        with ZipFile(BytesIO(payload)) as outer_zip:
            names = outer_zip.namelist()
            txt_name = _find_member(names, "TaxaSwap.txt")
            if txt_name is not None:
                return outer_zip.read(txt_name).decode("latin-1")

            inner_name = _find_member(names, ".ex_")
            if inner_name is None:
                raise B3CurveError("ZIP da B3 não contém arquivo .ex_ nem TaxaSwap.txt.")
            inner_payload = outer_zip.read(inner_name)
    except BadZipFile as exc:
        raise B3CurveError("Resposta da B3 não pôde ser aberta como ZIP.") from exc

    try:
        with ZipFile(BytesIO(inner_payload)) as inner_zip:
            txt_name = _find_member(inner_zip.namelist(), "TaxaSwap.txt")
            if txt_name is None:
                raise B3CurveError("Arquivo .ex_ da B3 não contém TaxaSwap.txt.")
            return inner_zip.read(txt_name).decode("latin-1")
    except BadZipFile as exc:
        raise B3CurveError("Arquivo .ex_ da B3 não pôde ser aberto como ZIP.") from exc


def _find_member(names: Sequence[str], suffix: str) -> str | None:
    suffix_lower = suffix.lower()
    for name in names:
        if name.lower().endswith(suffix_lower):
            return name
    return None


def _looks_like_zip(payload: bytes) -> bool:
    return payload[:2] == b"PK"


def _parse_taxaswap_line(line: str) -> dict[str, str]:
    offsets = (
        ("id_transacao", 6),
        ("compl", 3),
        ("tipo_registro", 2),
        ("data_geracao_arquivo", 8),
        ("cod_curvas", 2),
        ("cod_taxa", 5),
        ("desc", 15),
        ("num_dias_corridos", 5),
        ("num_dias_saques", 5),
        ("sinal_taxa", 1),
        ("taxa_teorica", 14),
        ("carat_vertice", 1),
        ("cod_vertice", 5),
    )
    parsed: dict[str, str] = {}
    position = 0
    for field, width in offsets:
        parsed[field] = line[position : position + width].strip()
        position += width
    return parsed


def _parse_yyyymmdd(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise B3CurveError(f"Data inválida no arquivo TaxaSwap: {value!r}.") from exc


def _parse_taxaswap_rate(sign: str, raw_rate: str) -> float:
    try:
        rate_percent = int(raw_rate) / 10_000_000.0
    except ValueError as exc:
        raise B3CurveError(f"Taxa inválida no arquivo TaxaSwap: {raw_rate!r}.") from exc
    multiplier = -1.0 if sign == "-" else 1.0
    return multiplier * rate_percent / 100.0


def _dedupe_and_sort_points(points: Sequence[B3CurvePoint]) -> list[B3CurvePoint]:
    by_du: dict[int, B3CurvePoint] = {}
    for point in sorted(points, key=lambda item: (item.du, item.dc)):
        existing = by_du.get(point.du)
        if existing is not None and abs(existing.rate_aa - point.rate_aa) > 1e-12:
            raise B3CurveError(f"Curva TaxaSwap contém DU duplicado com taxas diferentes: {point.du}.")
        by_du[point.du] = point
    return [by_du[du] for du in sorted(by_du)]


def _validate_points(points: Sequence[B3CurvePoint], curve_code: str) -> None:
    if len(points) < 2:
        raise B3CurveError(f"Curva {curve_code} tem menos de dois vértices.")
    previous_du = -1
    for point in points:
        if point.du <= previous_du:
            raise B3CurveError(f"Curva {curve_code} não está ordenada por dias úteis.")
        if point.du <= 0:
            raise B3CurveError(f"Curva {curve_code} contém DU não positivo: {point.du}.")
        if not -0.5 < point.rate_aa < 5.0:
            raise B3CurveError(f"Curva {curve_code} contém taxa fora de faixa plausível: {point.rate_aa:.6f}.")
        previous_du = point.du
