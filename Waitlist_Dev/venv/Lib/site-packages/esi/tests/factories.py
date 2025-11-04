from bravado.exception import (
    HTTPBadGateway,
    HTTPBadRequest,
    HTTPForbidden,
    HTTPGatewayTimeout,
    HTTPInternalServerError,
    HTTPNotFound,
    HTTPServiceUnavailable,
    HTTPUnauthorized,
)


def create_http_error(http_code: int, text: str = None) -> Exception:
    """Build a HTTP exception for django-esi from given http code."""
    exc_map = {
        400: HTTPBadRequest,
        401: HTTPUnauthorized,
        403: HTTPForbidden,
        404: HTTPNotFound,
        500: HTTPInternalServerError,
        502: HTTPBadGateway,
        503: HTTPServiceUnavailable,
        504: HTTPGatewayTimeout,
    }
    try:
        http_exc = exc_map[http_code]
    except KeyError:
        raise NotImplementedError(f"Unknown http code: {http_code}") from None
    if not text:
        text = "Test exception"
    return http_exc(response=BravadoResponseStub(http_code, text))


class BravadoResponseStub:
    """Stub for IncomingResponse in bravado, e.g. for HTTPError exceptions."""

    def __init__(
        self, status_code, reason="", text="", headers=None, raw_bytes=None
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.text = text
        self.headers = headers if headers else dict()
        self.raw_bytes = raw_bytes

    def __str__(self) -> str:
        return f"{self.status_code} {self.reason}"
