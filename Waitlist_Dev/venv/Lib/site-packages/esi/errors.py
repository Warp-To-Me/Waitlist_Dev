class DjangoEsiException(Exception):
    pass


class TokenError(DjangoEsiException):
    pass


class TokenInvalidError(TokenError):
    pass


class TokenExpiredError(TokenError):
    pass


class NotRefreshableTokenError(TokenError):
    pass


class IncompleteResponseError(DjangoEsiException):
    pass
