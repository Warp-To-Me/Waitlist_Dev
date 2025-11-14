"""
Custom exceptions for the ESI service.
"""

class EsiException(Exception):
    """Base exception for all ESI-related errors."""
    def __init__(self, message="An ESI error occurred.", status_code=500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class EsiTokenAuthFailure(EsiException):
    """
    Raised when an ESI token is invalid, revoked, or fails to refresh.
    This should trigger a re-authentication flow for the user.
    """
    def __init__(self, message="ESI token is invalid or revoked.", status_code=401):
        super().__init__(message, status_code)

class EsiScopeMissing(EsiException):
    """
    Raised when a token is valid but lacks the required scopes for an operation.
    """
    def __init__(self, message="Missing required ESI scopes.", status_code=403):
        super().__init__(message, status_code)

class EsiForbidden(EsiException):
    """
    Raised on an ESI 403 Forbidden error.
    This means the character does not have the *roles* to perform an action
    (e.g., is not an FC).
    """
    def __init__(self, message="ESI Forbidden: You may not have the required roles.", status_code=403):
        super().__init__(message, status_code)

class EsiNotFound(EsiException):
    """
    Raised on an ESI 404 Not Found error.
    The requested resource (e.g., fleet, character) does not exist.
    """
    def __init__(self, message="ESI Error: Resource not found.", status_code=404):
        super().__init__(message, status_code)