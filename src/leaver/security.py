"""Token handling, in-memory wiping, session fingerprinting and rate-limit primitives."""

from __future__ import annotations

import asyncio
import base64
import ctypes
import hashlib
import hmac
import json
import os
import platform
import re
import sys
import time
import uuid
from getpass import getpass
from types import TracebackType

import httpx
import questionary
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent, merge_key_bindings

from .i18n import t
from .utils import HEADER_RESET_JITTER, GoBack, console, secure_uniform

#: Basic Discord user-token shape: ``<user id b64>.<timestamp>.<hmac>``.
#: The first segment is 24 chars for older accounts and up to 26+ for newer (19-digit) IDs.
TOKEN_PATTERN: re.Pattern[str] = re.compile(r"[\w-]{24,28}\.[\w-]{6}\.[\w-]{27,38}")

#: Environment variable that may (insecurely) carry the token.
TOKEN_ENV_VAR: str = "DSL_TOKEN"


#: SHA-256 integrity digest of ``__author__`` + the ``ZODI4CTVN`` banner lines.
_SIGNATURE_DIGEST: str = "61c582451127acce111dc3089c4188486254ecb2ce05b54b5d4ef5f8352f1074"


class TokenError(Exception):
    """Raised when a token is missing or malformed."""


class TokenRevokedError(Exception):
    """Raised when Discord answers HTTP 401 — the token is invalid or has been revoked."""


class SignatureError(Exception):
    """Raised when the author attribution or banner signature has been modified."""


def verify_signature(author: str, banner_lines: tuple[str, ...]) -> None:
    """Verify that the author metadata and banner signature have not been tampered with.

    Raises:
        SignatureError: If the SHA-256 digest does not match the original ``zodi4ctvn`` release.
    """
    payload = f"{author}\n".encode() + "\n".join(banner_lines).encode()
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, _SIGNATURE_DIGEST):
        raise SignatureError(
            "Integrity check failed: author signature has been modified. "
            "Original project: https://github.com/zodi4ctvn/discord-server-leaver"
        )


# --------------------------------------------------------------------------- #
# Memory wiping
# --------------------------------------------------------------------------- #
def _buffer_address(value: str | bytes) -> int | None:
    """Return the address of the raw character buffer of a CPython ``str``/``bytes``.

    Only compact ASCII strings and ``bytes`` objects are supported, because their payload
    sits at the very end of the object (``sizeof - len - 1``). ``None`` is returned for
    anything that cannot be wiped safely.
    """
    if platform.python_implementation() != "CPython" or len(value) <= 1:
        return None
    if isinstance(value, str) and not value.isascii():
        return None
    return id(value) + sys.getsizeof(value) - len(value) - 1


def secure_wipe(value: str | bytes | bytearray | None) -> None:
    """Overwrite the memory backing ``value`` with ``\\x00`` bytes (best effort).

    Python strings are immutable, so this pokes the CPython object buffer directly via
    :mod:`ctypes`. Before writing, the buffer is read back and compared with the expected
    content; if it does not match, nothing is touched. After calling this the object must
    no longer be used — callers should drop every reference to it immediately.

    Args:
        value: The secret to wipe. ``None`` is ignored.
    """
    if value is None:
        return
    if isinstance(value, bytearray):
        for i in range(len(value)):
            value[i] = 0
        return
    try:
        address = _buffer_address(value)
        if address is None:
            return
        expected = value.encode("ascii") if isinstance(value, str) else bytes(value)
        size = len(expected)
        if ctypes.string_at(address, size) != expected:
            return  # Unexpected layout — refuse to write to unknown memory.
        ctypes.memset(address, 0, size)
    except Exception:  # wiping must never crash the shutdown path
        return


# --------------------------------------------------------------------------- #
# Token acquisition
# --------------------------------------------------------------------------- #
def validate_token_format(token: str) -> bool:
    """Return ``True`` if ``token`` looks like a Discord user token.

    Bot tokens (``Bot `` prefix) are rejected — this is a user-account tool only.
    """
    if not token or token.lower().startswith("bot "):
        return False
    return TOKEN_PATTERN.fullmatch(token) is not None


_TOKEN_PROMPT_STYLE = questionary.Style(
    [
        ("qmark", "fg:ansimagenta bold"),
        ("question", "bold"),
        ("answer", "fg:ansigreen"),
    ]
)


def _read_clipboard() -> str:
    """Read plain text from the OS clipboard (Windows ``user32`` via ``ctypes``)."""
    if sys.platform != "win32":
        return ""
    cf_unicodetext = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool

    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(cf_unicodetext)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return str(ctypes.wstring_at(ptr))
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def clipboard_has_token(token: str) -> bool:
    """Return ``True`` if the Windows clipboard currently contains ``token``."""
    if sys.platform != "win32" or not token:
        return False
    clip = _read_clipboard().strip().strip('"').strip("'")
    matched = hmac.compare_digest(clip, token)
    secure_wipe(clip)
    return matched


def clear_clipboard() -> bool:
    """Clear the Windows clipboard (with brief retries if another app holds the lock)."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool

    for _ in range(5):
        if user32.OpenClipboard(None):
            try:
                return bool(user32.EmptyClipboard())
            finally:
                user32.CloseClipboard()
        time.sleep(0.03)
    return False


def _prompt_masked_token() -> str:
    """Read the token via a masked prompt (``*``) with Ctrl+V paste and Backspace/Esc back."""
    if not sys.stdin.isatty():
        return getpass(t("token_prompt"))

    question = questionary.password(t("token_prompt"), style=_TOKEN_PROMPT_STYLE)
    back_kb = KeyBindings()
    buf_empty = Condition(lambda: len(question.application.current_buffer.text) == 0)

    @back_kb.add("c-v")
    def _paste(event: KeyPressEvent) -> None:
        text = _read_clipboard().strip()
        if text:
            event.current_buffer.insert_text(text)

    @back_kb.add("backspace", filter=buf_empty)
    @back_kb.add("escape", eager=True)
    def _go_back(event: KeyPressEvent) -> None:
        event.app.exit(exception=GoBack())

    existing = question.application.key_bindings
    question.application.key_bindings = (
        merge_key_bindings([back_kb, existing]) if existing is not None else back_kb
    )
    try:
        value: str = question.unsafe_ask()
    finally:
        question.application.current_buffer.reset()
    return value


def acquire_token() -> str:
    """Obtain the user token from a masked prompt (or from ``DSL_TOKEN`` if explicitly set).

    The token is never accepted via CLI arguments or config files. If ``DSL_TOKEN`` is
    present in the process environment the user is warned that this is insecure, and the
    variable is removed from the process environment after reading.

    Raises:
        GoBack: If the user presses Esc or Backspace on an empty input (or empty Enter).
        TokenError: If the token is empty or has an invalid format.
    """
    raw = os.environ.pop(TOKEN_ENV_VAR, None)
    from_env = bool(raw)
    if raw:
        console.print(f"[yellow]{t('env_warning', var=TOKEN_ENV_VAR)}[/yellow]")
    else:
        raw = _prompt_masked_token()

    token = raw.strip().strip('"').strip("'")
    if token is not raw:
        secure_wipe(raw)
    del raw

    if not token and not from_env:
        raise GoBack()

    if not validate_token_format(token):
        secure_wipe(token)
        raise TokenError(t("err_token_format"))
    return token


class TokenSession:
    """Owns the user token for the lifetime of one run and wipes it on exit.

    Use as a context manager so the token is wiped on normal exit *and* on exceptions::

        with TokenSession(acquire_token()) as session:
            ...
    """

    __slots__ = ("_token",)

    def __init__(self, token: str) -> None:
        """Create a session holding ``token`` (already validated)."""
        self._token: str | None = token

    @property
    def token(self) -> str:
        """Return the token. Raises :class:`TokenError` if it has already been wiped."""
        if self._token is None:
            raise TokenError("Token has been wiped.")
        return self._token

    @property
    def active(self) -> bool:
        """Whether the token is still held in memory."""
        return self._token is not None

    def wipe(self) -> None:
        """Overwrite the token in memory with ``\\x00`` and drop the reference."""
        if self._token is not None:
            secure_wipe(self._token)
            self._token = None

    def __enter__(self) -> TokenSession:
        """Enter the context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Wipe the token regardless of how the context exits."""
        self.wipe()

    def __repr__(self) -> str:
        """Never expose the token in reprs / tracebacks."""
        return f"<TokenSession active={self.active}>"


# --------------------------------------------------------------------------- #
# Per-session client fingerprint
# --------------------------------------------------------------------------- #
_LOCALES: tuple[str, ...] = ("en-US", "en-GB", "tr", "de", "fr", "es-ES", "pt-BR", "nl", "pl")


def _pick(options: tuple[str, ...]) -> str:
    """Pick an element using :func:`os.urandom` entropy."""
    return options[int.from_bytes(os.urandom(2), "big") % len(options)]


def build_user_agent(chrome_major: int) -> str:
    """Return the browser User-Agent string for a given Chrome major version."""
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36"
    )


def generate_fingerprint() -> tuple[str, str]:
    """Generate a fresh, realistic client fingerprint for this session.

    Returns:
        A ``(user_agent, x_super_properties)`` tuple, where the second element is the
        base64-encoded JSON blob Discord's web client sends in ``X-Super-Properties``.
    """
    chrome_major = int(secure_uniform(128, 137))
    user_agent = build_user_agent(chrome_major)
    properties = {
        "os": "Windows",
        "browser": "Chrome",
        "device": "",
        "system_locale": _pick(_LOCALES),
        "has_client_mods": False,
        "browser_user_agent": user_agent,
        "browser_version": f"{chrome_major}.0.0.0",
        "os_version": "10",
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": "stable",
        "client_build_number": int(secure_uniform(340_000, 390_000)),
        "client_event_source": None,
        "client_launch_id": str(uuid.uuid4()),
        "client_heartbeat_session_id": str(uuid.uuid4()),
    }
    encoded = base64.b64encode(
        json.dumps(properties, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return user_agent, encoded


# --------------------------------------------------------------------------- #
# Rate limiting — Layer 1 (Discord headers)
# --------------------------------------------------------------------------- #
class HeaderRateLimiter:
    """Layer 1 of the rate-limit engine: obey ``X-RateLimit-*`` response headers."""

    def __init__(self) -> None:
        """Create a limiter with no pending wait."""
        self.total_waited: float = 0.0

    @staticmethod
    def _float_header(response: httpx.Response, name: str) -> float | None:
        """Parse a numeric header, returning ``None`` if absent or malformed."""
        value = response.headers.get(name)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    async def observe(self, response: httpx.Response) -> float:
        """Inspect ``response`` and sleep if the current bucket is exhausted.

        If ``X-RateLimit-Remaining`` is ``0`` the limiter sleeps
        ``X-RateLimit-Reset-After`` seconds plus up to 0.1 s of jitter.

        Returns:
            Seconds slept (``0.0`` if no wait was needed).
        """
        remaining = self._float_header(response, "X-RateLimit-Remaining")
        reset_after = self._float_header(response, "X-RateLimit-Reset-After")
        if remaining is None or reset_after is None or remaining > 0:
            return 0.0
        wait = reset_after + secure_uniform(0.0, HEADER_RESET_JITTER)
        await asyncio.sleep(wait)
        self.total_waited += wait
        return wait
