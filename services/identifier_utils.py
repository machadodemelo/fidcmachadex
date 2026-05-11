from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


_BLANK_VALUES = {"", "nan", "none", "<na>"}
_CNPJ_TRAILING_DECIMAL_RE = re.compile(r"^(\d{14})[.,]0+$")
_CNPJ_LEADING_ZERO_DECIMAL_RE = re.compile(r"^(\d{13})[.,]0+$")


def normalize_cnpj_digits(value: object) -> str:
    """Return a canonical 14-digit CNPJ string when the input is recoverable.

    The helper is intentionally conservative: it preserves leading zeros when
    they are present in the raw textual representation and only normalizes
    decimal/scientific artifacts when the result is unequivocally a CNPJ.
    """

    if value is None:
        return ""
    raw = str(value).strip()
    if raw.lower() in _BLANK_VALUES:
        return ""
    if re.fullmatch(r"\d{14}", raw):
        return raw
    trailing_decimal = _CNPJ_TRAILING_DECIMAL_RE.fullmatch(raw)
    if trailing_decimal:
        return trailing_decimal.group(1)
    leading_zero_decimal = _CNPJ_LEADING_ZERO_DECIMAL_RE.fullmatch(raw)
    if leading_zero_decimal:
        return leading_zero_decimal.group(1).zfill(14)
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 14:
        return digits
    try:
        numeric = Decimal(raw)
    except (InvalidOperation, ValueError):
        return ""
    if numeric != numeric.to_integral_value():
        return ""
    integer_text = format(numeric.quantize(Decimal("1")), "f")
    if "." in integer_text:
        integer_text = integer_text.split(".", 1)[0]
    integer_text = integer_text.strip()
    return integer_text if re.fullmatch(r"\d{14}", integer_text) else ""


def format_cnpj(value: object, *, fallback: str = "N/D") -> str:
    normalized = normalize_cnpj_digits(value)
    if not normalized:
        raw = str(value or "").strip()
        return raw or fallback
    return f"{normalized[:2]}.{normalized[2:5]}.{normalized[5:8]}/{normalized[8:12]}-{normalized[12:]}"
