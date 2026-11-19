"""Discord REST API layer (raw HTTP via httpx — no Discord libraries)."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Any

import httpx

from .i18n import t
from .security import (
    HeaderRateLimiter,
    TokenRevokedError,
    TokenSession,
    secure_wipe,
)
from .utils import backoff_429

BASE_URL: str = "https://discord.com/api/v10"
GUILD_PAGE_LIMIT: int = 200

MAX_429_RETRIES: int = 5
MAX_5XX_RETRIES: int = 3
SERVER_ERROR_DELAY: float = 5.0


class APIError(Exception):
    """Raised when a request ultimately fails (after retries) with a non-success status."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Create an error with an optional HTTP status code."""
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class User:
    """The authenticated Discord user."""

    id: str
    username: str
    discriminator: str
    global_name: str | None

    @property
    def tag(self) -> str:
        """Return ``Username#0000`` (``#0`` accounts show as ``Username#0000``)."""
        disc = self.discriminator if self.discriminator not in ("", "0") else "0000"
        return f"{self.username}#{disc}"


#: Discord permission bitflags (returned on ``GET /users/@me/guilds``).
PERM_KICK_MEMBERS: int = 1 << 1
PERM_BAN_MEMBERS: int = 1 << 2
PERM_ADMINISTRATOR: int = 1 << 3
PERM_MANAGE_CHANNELS: int = 1 << 4
PERM_MANAGE_GUILD: int = 1 << 5
PERM_MANAGE_MESSAGES: int = 1 << 13
PERM_MUTE_MEMBERS: int = 1 << 22
PERM_DEAFEN_MEMBERS: int = 1 << 23
PERM_MOVE_MEMBERS: int = 1 << 24
PERM_MANAGE_NICKNAMES: int = 1 << 27
PERM_MANAGE_ROLES: int = 1 << 28
PERM_MODERATE_MEMBERS: int = 1 << 40
PERM_STAFF_MASK: int = (
    PERM_KICK_MEMBERS
    | PERM_BAN_MEMBERS
    | PERM_MANAGE_CHANNELS
    | PERM_MANAGE_GUILD
    | PERM_MANAGE_MESSAGES
    | PERM_MUTE_MEMBERS
    | PERM_DEAFEN_MEMBERS
    | PERM_MOVE_MEMBERS
    | PERM_MANAGE_NICKNAMES
    | PERM_MANAGE_ROLES
    | PERM_MODERATE_MEMBERS
)


@dataclass(frozen=True, slots=True)
class Guild:
    """A Discord guild (server). Only the fields this tool needs are kept."""

    id: str
    name: str
    owner: bool
    icon: str | None
    permissions: int = 0

    @property
    def is_admin(self) -> bool:
        """Whether the user has the Administrator permission (and is not the owner)."""
        return not self.owner and bool(self.permissions & PERM_ADMINISTRATOR)

    @property
    def is_staff(self) -> bool:
        """Whether the user has Manage Server / Ban / Kick permissions (non-owner, non-admin)."""
        return not self.owner and not self.is_admin and bool(self.permissions & PERM_STAFF_MASK)


class LeaveStatus(Enum):
    """Outcome of a single leave attempt."""

    LEFT = "left"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LeaveResult:
    """Result of attempting to leave one guild."""

    guild: Guild
    status: LeaveStatus
    detail: str = ""
    owner_skip: bool = False


class DiscordClient:
    """Minimal async Discord REST client for a *user* token.

    Only three endpoints are ever called: ``GET /users/@me``, ``GET /users/@me/guilds`` and
    ``DELETE /users/@me/guilds/{id}``. Every request goes through the header-based limiter
    (layer 1) and the 429 / 5xx retry handler (layer 3).
    """

    def __init__(self, session: TokenSession, fingerprint: tuple[str, str]) -> None:
        """Create a client bound to ``session``; the HTTP pool opens on ``__aenter__``.

        Args:
            session: The token session that owns the user token.
            fingerprint: ``(user_agent, x_super_properties)`` generated once per run by
                :func:`leaver.security.generate_fingerprint`.
        """
        self._session = session
        self._fingerprint = fingerprint
        self._limiter = HeaderRateLimiter()
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ lifecycle
    async def __aenter__(self) -> DiscordClient:
        """Open the HTTP/2 connection pool using this session's fingerprint."""
        user_agent, super_properties = self._fingerprint
        headers = {
            "Authorization": self._session.token,  # user token — never a "Bot " prefix
            "Content-Type": "application/json",
            "User-Agent": user_agent,
            "X-Super-Properties": super_properties,
        }
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=headers,
            http2=True,
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=False,
            trust_env=False,  # never route through env-configured proxies
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the pool and wipe the encoded Authorization header copy."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client and wipe the token copy held in its default headers."""
        if self._http is None:
            return
        http, self._http = self._http, None
        try:
            await http.aclose()
        finally:
            with contextlib.suppress(Exception):  # best effort only
                for key, value in http.headers.raw:
                    if key.lower() == b"authorization":
                        secure_wipe(value)

    # ------------------------------------------------------------------ core request
    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        """Extract ``retry_after`` (seconds) from a 429 body, falling back to headers."""
        try:
            body = response.json()
            if isinstance(body, dict) and "retry_after" in body:
                return float(body["retry_after"])
        except (ValueError, TypeError):
            pass
        for header in ("Retry-After", "X-RateLimit-Reset-After"):
            value = response.headers.get(header)
            if value:
                try:
                    return float(value)
                except ValueError:
                    continue
        return 1.0

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a request with layer 1 + layer 3 rate-limit handling.

        Raises:
            TokenRevokedError: On HTTP 401.
            APIError: When 429 / 5xx / network retries are exhausted.
        """
        if self._http is None:
            raise RuntimeError("DiscordClient used outside of 'async with'.")

        attempts_429 = 0
        attempts_5xx = 0
        while True:
            try:
                response = await self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempts_5xx >= MAX_5XX_RETRIES:
                    raise APIError(t("err_network", name=type(exc).__name__)) from None
                attempts_5xx += 1
                await asyncio.sleep(SERVER_ERROR_DELAY)
                continue

            # Layer 1 — honour the bucket headers on every response.
            await self._limiter.observe(response)

            status = response.status_code
            if status == 401:
                raise TokenRevokedError(t("err_401"))

            if status == 429:
                if attempts_429 >= MAX_429_RETRIES:
                    raise APIError(t("err_429"), status)
                await asyncio.sleep(backoff_429(self._retry_after(response), attempts_429))
                attempts_429 += 1
                continue

            if 500 <= status < 600:
                if attempts_5xx >= MAX_5XX_RETRIES:
                    raise APIError(t("err_5xx", status=status), status)
                attempts_5xx += 1
                await asyncio.sleep(SERVER_ERROR_DELAY)
                continue

            return response

    # ------------------------------------------------------------------ endpoints
    async def get_me(self) -> User:
        """Validate the token and return the authenticated user (``GET /users/@me``)."""
        response = await self._request("GET", "/users/@me")
        if response.status_code != 200:
            raise APIError(t("err_account", status=response.status_code), response.status_code)
        data = response.json()
        if data.get("bot"):
            raise APIError(t("err_bot"))
        return User(
            id=str(data["id"]),
            username=str(data.get("username", "unknown")),
            discriminator=str(data.get("discriminator", "0")),
            global_name=data.get("global_name"),
        )

    async def fetch_guilds(self) -> list[Guild]:
        """Return every guild the user is in, following the ``after`` cursor until exhausted."""
        guilds: list[Guild] = []
        after: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": GUILD_PAGE_LIMIT}
            if after is not None:
                params["after"] = after
            response = await self._request("GET", "/users/@me/guilds", params=params)
            if response.status_code != 200:
                raise APIError(t("err_guilds", status=response.status_code), response.status_code)
            page = response.json()
            if not isinstance(page, list) or not page:
                break
            for raw in page:
                raw_perms = raw.get("permissions", 0)
                try:
                    perms = int(raw_perms)
                except (TypeError, ValueError):
                    perms = 0
                guilds.append(
                    Guild(
                        id=str(raw["id"]),
                        name=str(raw.get("name", "Unknown server")),
                        owner=bool(raw.get("owner", False)),
                        icon=raw.get("icon"),
                        permissions=perms,
                    )
                )
            if len(page) < GUILD_PAGE_LIMIT:
                break
            after = str(page[-1]["id"])
        return guilds

    async def leave_guild(self, guild: Guild) -> LeaveResult:
        """Leave ``guild`` (``DELETE /users/@me/guilds/{id}``).

        Owned guilds are skipped without any request. HTTP 403 is reported as a skip;
        exhausted 429 / 5xx retries are reported as errors. HTTP 401 propagates as
        :class:`TokenRevokedError` so the caller can abort immediately.
        """
        if guild.owner:
            return LeaveResult(guild, LeaveStatus.SKIPPED, t("detail_owner"), owner_skip=True)
        try:
            response = await self._request(
                "DELETE", f"/users/@me/guilds/{guild.id}", json={"lurking": False}
            )
        except APIError as exc:
            return LeaveResult(guild, LeaveStatus.ERROR, str(exc))

        status = response.status_code
        if status in (200, 204):
            return LeaveResult(guild, LeaveStatus.LEFT, t("detail_left"))
        if status == 403:
            return LeaveResult(guild, LeaveStatus.SKIPPED, t("detail_forbidden", name=guild.name))
        if status == 404:
            return LeaveResult(guild, LeaveStatus.ERROR, t("detail_404"))
        return LeaveResult(guild, LeaveStatus.ERROR, t("detail_unexpected", status=status))
