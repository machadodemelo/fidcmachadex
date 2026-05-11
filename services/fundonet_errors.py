from __future__ import annotations


class FundosNetError(Exception):
    """Base error for Fundos.NET integration."""

    def __init__(self, message: str, *, details: dict | None = None, trace: list[dict] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.trace = trace or []


class InvalidCnpjError(FundosNetError):
    """Raised when CNPJ input is invalid."""


class ProviderUnavailableError(FundosNetError):
    """Raised when provider endpoint is unavailable or unstable."""


class AuthenticationRequiredError(FundosNetError):
    """Raised when endpoint indicates session/captcha/auth requirement."""


class FundoNotFoundError(FundosNetError):
    """Raised when no fund can be matched for a CNPJ."""


class NoDocumentsFoundError(FundosNetError):
    """Raised when no relevant documents are found."""


class DocumentDownloadError(FundosNetError):
    """Raised when a document cannot be downloaded."""


class DocumentParseError(FundosNetError):
    """Raised when XML document cannot be parsed."""
