from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from hashlib import sha256
import html
import re
from typing import Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


B3_TRADING_CALENDAR_URL = "https://www.b3.com.br/en_us/solutions/platforms/puma-trading-system/for-members-and-traders/trading-calendar/holidays/"
B3_CALENDAR_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


class B3CalendarError(RuntimeError):
    """Raised when the B3 trading calendar cannot be fetched or parsed."""


@dataclass(frozen=True)
class B3CalendarSnapshot:
    holidays: tuple[date, ...]
    official_years: tuple[int, ...]
    projected_years: tuple[int, ...]
    source_url: str
    retrieved_at: datetime
    content_sha256: str


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def networkdays(start: date, end: date, feriados: Iterable[date | datetime]) -> int:
    if start > end:
        start, end = end, start
    feriados_set = {_as_date(holiday) for holiday in feriados}
    day = start
    total = 0
    while day <= end:
        if day.weekday() < 5 and day not in feriados_set:
            total += 1
        day = day.fromordinal(day.toordinal() + 1)
    return total


def build_period_indexes(length: int) -> list[int]:
    indices = [0]
    for i in range(1, length):
        if i <= 4:
            indices.append(6 * i)
        else:
            indices.append(24 + (i - 4))
    return indices


def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def b3_market_holidays_for_year(year: int) -> set[date]:
    easter = easter_date(year)
    holidays = {
        date(year, 1, 1),
        date(year, 4, 21),
        date(year, 5, 1),
        date(year, 9, 7),
        date(year, 10, 12),
        date(year, 11, 2),
        date(year, 11, 15),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 31),
        easter - timedelta(days=48),  # Carnival Monday
        easter - timedelta(days=47),  # Carnival Tuesday
        easter - timedelta(days=2),  # Good Friday
        easter + timedelta(days=60),  # Corpus Christi
    }
    if year >= 2024:
        holidays.add(date(year, 11, 20))
    return holidays


def b3_market_holidays_for_dates(datas: Sequence[datetime | date]) -> set[date]:
    if not datas:
        return set()
    years = range(min(_as_date(value).year for value in datas), max(_as_date(value).year for value in datas) + 1)
    holidays: set[date] = set()
    for year in years:
        holidays.update(b3_market_holidays_for_year(year))
    return holidays


def fetch_b3_trading_calendar_html(timeout: float = 30.0) -> tuple[str, str]:
    request = Request(
        B3_TRADING_CALENDAR_URL,
        headers={
            "User-Agent": "fidc-streamlit-model/1.0",
            "Accept": "text/html, */*",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise B3CalendarError(f"B3 retornou HTTP {exc.code} ao consultar o calendário de negociação.") from exc
    except URLError as exc:
        raise B3CalendarError(f"Falha de rede ao consultar calendário B3: {exc.reason}.") from exc
    except OSError as exc:
        raise B3CalendarError(f"Falha ao consultar calendário B3: {exc}.") from exc
    if not payload:
        raise B3CalendarError("B3 retornou calendário de negociação vazio.")
    return payload.decode("utf-8", errors="replace"), sha256(payload).hexdigest()


def parse_b3_trading_calendar_holidays(html_text: str, years: Sequence[int]) -> dict[int, set[date]]:
    parsed: dict[int, set[date]] = {}
    matches = list(re.finditer(r"<h2>\s*Market Calendar (\d{4})\s*</h2>", html_text, flags=re.IGNORECASE))
    for index, match in enumerate(matches):
        year = int(match.group(1))
        if year not in years:
            continue
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(html_text)
        parsed[year] = _parse_b3_calendar_year_block(year, html_text[match.end() : block_end])
    return parsed


def build_b3_calendar_snapshot(
    datas: Sequence[datetime | date],
    html_text: str,
    *,
    content_hash: str = "",
    source_url: str = B3_TRADING_CALENDAR_URL,
    retrieved_at: datetime | None = None,
) -> B3CalendarSnapshot:
    years = tuple(range(min(_as_date(value).year for value in datas), max(_as_date(value).year for value in datas) + 1))
    parsed_by_year = parse_b3_trading_calendar_holidays(html_text, years)
    holidays: set[date] = set()
    official_years: list[int] = []
    projected_years: list[int] = []
    for year in years:
        parsed_holidays = parsed_by_year.get(year)
        if parsed_holidays:
            holidays.update(parsed_holidays)
            official_years.append(year)
        else:
            holidays.update(b3_market_holidays_for_year(year))
            projected_years.append(year)
    if not holidays:
        raise B3CalendarError("Calendário B3 não gerou feriados para o período do fluxo.")
    return B3CalendarSnapshot(
        holidays=tuple(sorted(holidays)),
        official_years=tuple(official_years),
        projected_years=tuple(projected_years),
        source_url=source_url,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        content_sha256=content_hash,
    )


def _parse_b3_calendar_year_block(year: int, block: str) -> set[date]:
    month_pattern = "|".join(B3_CALENDAR_MONTHS)
    holiday_dates: set[date] = set()
    current_month: int | None = None
    pattern = re.compile(rf"<a[^>]*>\s*({month_pattern})\s*</a>|<tr[^>]*>(.*?)</tr>", flags=re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(block):
        month_name = match.group(1)
        if month_name:
            current_month = B3_CALENDAR_MONTHS[month_name]
            continue
        if current_month is None:
            continue
        row = match.group(2) or ""
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 4:
            continue
        day_text = _clean_html_text(cells[0])
        if not day_text.isdigit():
            continue
        event_text = _clean_html_text(cells[1])
        description_text = _clean_html_text(cells[3])
        if _is_b3_non_trading_row(row, event_text, description_text):
            holiday_dates.add(date(year, current_month, int(day_text)))
    return holiday_dates


def _clean_html_text(value: str) -> str:
    without_noise = re.sub(r"<style.*?</style>|<script.*?</script>|<meta[^>]*>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_noise)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _is_b3_non_trading_row(raw_row: str, event_text: str, description_text: str) -> bool:
    combined = f"{event_text} {description_text}".lower()
    if "no trading" not in combined:
        return False
    if "listed b3" in combined:
        return True
    if "bm&fbovespa" in combined:
        return True
    if "no trading session" in event_text.lower():
        return True
    return "Portugu" in raw_row


def merge_with_b3_market_holidays(
    feriados: Iterable[date | datetime],
    datas: Sequence[datetime | date],
) -> list[date]:
    merged = {_as_date(holiday) for holiday in feriados}
    merged.update(b3_market_holidays_for_dates(datas))
    return sorted(merged)


def build_day_counts(datas: Sequence[datetime], feriados: Iterable[date | datetime]) -> tuple[list[int], list[int]]:
    if not datas:
        return [], []

    start_date = datas[0].date()
    holiday_dates = [_as_date(holiday) for holiday in feriados]
    dc = [(dt.date() - start_date).days for dt in datas]
    du = [0]
    for dt in datas[1:]:
        du.append(networkdays(start_date, dt.date(), holiday_dates) - 1)
    return dc, du
