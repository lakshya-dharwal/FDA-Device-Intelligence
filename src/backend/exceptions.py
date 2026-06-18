"""
Typed backend exceptions used to normalize failures across the API,
model provider, and OpenFDA integration layers.
"""


class BackendError(Exception):
    """Base class for API-facing application errors."""

    code = "internal_error"
    status_code = 500
    retryable = False
    default_message = "An unexpected internal error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        self.retryable = self.retryable if retryable is None else retryable
        self.status_code = self.status_code if status_code is None else status_code
        self.code = self.code if code is None else code
        super().__init__(self.message)

    def to_response(self, request_id: str | None = None) -> dict:
        payload = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if request_id:
            payload["request_id"] = request_id
        return {"error": payload}


class InvalidQueryError(BackendError):
    code = "invalid_query"
    status_code = 400
    default_message = "Query cannot be empty."


class FDAUpstreamError(BackendError):
    code = "fda_upstream_error"
    status_code = 502
    retryable = True
    default_message = "The FDA data source returned an upstream error."


class FDAUpstreamTimeoutError(BackendError):
    code = "fda_upstream_timeout"
    status_code = 504
    retryable = True
    default_message = "The FDA data source did not respond in time."


class ModelProviderError(BackendError):
    code = "model_provider_error"
    status_code = 502
    retryable = True
    default_message = "The AI model provider returned an upstream error."


class ModelProviderTimeoutError(BackendError):
    code = "model_provider_timeout"
    status_code = 504
    retryable = True
    default_message = "The AI model provider did not respond in time."


class InternalQueryError(BackendError):
    code = "internal_query_error"
    status_code = 500
    default_message = "The query could not be completed due to an internal error."
