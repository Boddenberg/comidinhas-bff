class AppError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class BadRequestError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            status_code=400,
            code="bad_request",
        )


class AuthenticationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            status_code=401,
            code="authentication_error",
        )


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            status_code=409,
            code="conflict",
        )


class ConfigurationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            status_code=500,
            code="configuration_error",
        )


class ExternalServiceError(AppError):
    def __init__(
        self,
        service_name: str,
        message: str,
        *,
        status_code: int = 502,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code="external_service_error",
        )
        self.service_name = service_name


class NotFoundError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            status_code=404,
            code="not_found",
        )
