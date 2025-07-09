from typing import Optional, Dict

class KworkException(Exception):
    """Базовое исключение для всех ошибок API Kwork"""
    def __init__(self, message: str = "Kwork API error", code: Optional[int] = None, details: Optional[Dict] = None, request_info: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        self.request_info = request_info or {}
        super().__init__(f"[{code}] {message}" if code else message)

class KworkAuthException(KworkException):
    """Ошибки аутентификации и авторизации"""
    def __init__(self, message: str = "Authentication failed", code: int = 401, **kwargs):
        super().__init__(message, code, **kwargs)

class KworkApiException(KworkException):
    """Ошибки обработки API запросов"""
    def __init__(self, message: str = "API request failed", code: int = 400, **kwargs):
        super().__init__(message, code, **kwargs)

class KworkRateLimitException(KworkApiException):
    """Превышение лимитов запросов"""
    def __init__(self, message: str = "Rate limit exceeded", code: int = 429, **kwargs):
        super().__init__(message, code, **kwargs)
        self.retry_after = kwargs.get('retry_after')

class KworkValidationException(KworkException):
    """Ошибки валидации входных данных"""
    def __init__(self, message: str = "Invalid input", code: int = 422, **kwargs):
        super().__init__(message, code, **kwargs)

class KworkConnectionException(KworkException):
    """Ошибки сетевого подключения"""
    def __init__(self, message: str = "Connection error", code: int = 500, **kwargs):
        super().__init__(message, code, **kwargs)

class KworkDataException(KworkException):
    """Ошибки обработки данных"""
    def __init__(self, message: str = "Data processing error", code: int = 500, **kwargs):
        super().__init__(message, code, **kwargs)