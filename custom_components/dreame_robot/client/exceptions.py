"""Exceptions raised by the Dreame client."""

from __future__ import annotations


class DreameError(Exception):
    """Base class for every client error."""


class DreameAuthError(DreameError):
    """Cloud rejected the supplied credentials."""


class DreameTwoFactorRequiredError(DreameAuthError):
    """The account requires a second factor, so password login is impossible."""

    def __init__(self, url: str) -> None:
        super().__init__("Two-factor authentication is enabled on this account")
        self.url = url


class DreameConnectionError(DreameError):
    """The cloud or the broker could not be reached."""


class DreameCommandRejectedError(DreameError):
    """The device understood the command and refused it."""


class DreameApiError(DreameError):
    """The cloud returned a non-zero API code."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(f"Cloud API error {code}{f': {message}' if message else ''}")
        self.code = code
