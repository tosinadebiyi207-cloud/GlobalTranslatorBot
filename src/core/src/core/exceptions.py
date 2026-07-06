"""
Custom exceptions for the application.
"""

from typing import Optional, Any


class TranslatorBotError(Exception):
    """Base exception for translator bot."""
    def __init__(self, message: str, code: Optional[str] = None, details: Optional[Any] = None):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(message)


class ConfigurationError(TranslatorBotError):
    """Configuration related errors."""
    pass


class DatabaseError(TranslatorBotError):
    """Database related errors."""
    pass


class TranslationError(TranslatorBotError):
    """Translation related errors."""
    pass


class RateLimitError(TranslatorBotError):
    """Rate limiting errors."""
    def __init__(self, message: str, retry_after: int):
        self.retry_after = retry_after
        super().__init__(message, code='RATE_LIMIT')


class OCRServiceError(TranslatorBotError):
    """OCR service errors."""
    pass


class VoiceServiceError(TranslatorBotError):
    """Voice service errors."""
    pass


class DocumentServiceError(TranslatorBotError):
    """Document service errors."""
    pass


class CacheError(TranslatorBotError):
    """Cache related errors."""
    pass


class ValidationError(TranslatorBotError):
    """Validation errors."""
    pass
