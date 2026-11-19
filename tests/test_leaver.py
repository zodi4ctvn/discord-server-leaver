"""Unit tests for Discord Server Leaver (utils, security, integrity, i18n, API)."""

from __future__ import annotations

import httpx
import pytest

from leaver import __author__
from leaver.api import DiscordClient, Guild, LeaveStatus
from leaver.i18n import STRINGS
from leaver.integrity import check_integrity, verify_integrity
from leaver.security import (
    SignatureError,
    TokenRevokedError,
    TokenSession,
    generate_fingerprint,
    secure_wipe,
    validate_token_format,
    verify_signature,
)
from leaver.ui import _BANNER_LINES
from leaver.utils import backoff_429, estimate_seconds, format_duration, next_delay


def _dummy_token() -> str:
    """Build a synthetic token-shaped string at runtime (never a literal secret)."""
    return ".".join(("A" * 24, "B" * 6, "C" * 27))


def test_signature_valid() -> None:
    verify_signature(__author__, _BANNER_LINES)


def test_signature_tampered_raises() -> None:
    with pytest.raises(SignatureError):
        verify_signature("someone_else", _BANNER_LINES)


def test_integrity_passes_default_and_frozen() -> None:
    assert check_integrity() == []
    assert check_integrity(is_frozen=True) == []


def test_integrity_detects_tampering_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "author_mismatch" in check_integrity(author="rebrander", is_frozen=True)
    assert "package_renamed" in check_integrity(package_name="stolen_pkg", is_frozen=True)
    bad_strings = {
        "en": {"sel_title": "Stolen Tool"},
        "tr": {"sel_title": "Çalıntı Araç"},
    }
    violations = check_integrity(strings=bad_strings, is_frozen=True)
    assert "i18n_project_name_missing:en" in violations
    assert "i18n_project_name_missing:tr" in violations

    monkeypatch.setattr("leaver.integrity.check_integrity", lambda: ["author_mismatch"])
    with pytest.raises(SystemExit) as exc_info:
        verify_integrity()
    assert exc_info.value.code == 1


def test_token_format_validation() -> None:
    valid_token = _dummy_token()
    assert validate_token_format(valid_token) is True
    assert validate_token_format(f"Bot {valid_token}") is False
    assert validate_token_format("short") is False
    assert validate_token_format("") is False


def test_token_session_and_secure_wipe() -> None:
    token = _dummy_token()
    with TokenSession(token) as session:
        assert session.active is True
        assert "TokenSession" in repr(session)
        assert token not in repr(session)
    assert session.active is False

    buf = bytearray(b"secret-bytes")
    secure_wipe(buf)
    assert all(b == 0 for b in buf)


def test_utils_delays_and_formatting() -> None:
    assert next_delay(5, 5) == 0.0
    assert next_delay(1, 5) > 0.0
    assert estimate_seconds(0) == 0.0
    assert estimate_seconds(10) > 0.0
    assert format_duration(45.2) == "45s"
    assert format_duration(125.0) == "2m 05s"
    assert format_duration(3665.0) == "1h 01m"
    assert backoff_429(1.0, 2) >= 2.25


def test_i18n_key_parity() -> None:
    assert set(STRINGS["en"]) == set(STRINGS["tr"])


@pytest.mark.asyncio
async def test_leave_guild_statuses_including_404_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/100"):
            return httpx.Response(204)
        if request.url.path.endswith("/403"):
            return httpx.Response(403)
        if request.url.path.endswith("/404"):
            return httpx.Response(404)
        if request.url.path.endswith("/401"):
            return httpx.Response(401)
        return httpx.Response(500)

    session = TokenSession(_dummy_token())
    client = DiscordClient(session, generate_fingerprint())
    client._http = httpx.AsyncClient(
        base_url="https://discord.com/api/v10",
        transport=httpx.MockTransport(handler),
    )
    try:
        res_owner = await client.leave_guild(Guild("1", "Owned", owner=True, icon=None))
        assert res_owner.status is LeaveStatus.SKIPPED
        assert res_owner.owner_skip is True

        res_ok = await client.leave_guild(Guild("100", "Regular", owner=False, icon=None))
        assert res_ok.status is LeaveStatus.LEFT

        res_403 = await client.leave_guild(Guild("403", "Forbidden", owner=False, icon=None))
        assert res_403.status is LeaveStatus.SKIPPED

        res_404 = await client.leave_guild(Guild("404", "AlreadyGone", owner=False, icon=None))
        assert res_404.status is LeaveStatus.SKIPPED

        with pytest.raises(TokenRevokedError):
            await client.leave_guild(Guild("401", "Revoked", owner=False, icon=None))
    finally:
        await client.aclose()
        session.wipe()


@pytest.mark.asyncio
async def test_client_429_does_not_double_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429 must only sleep via backoff_429 and NOT via HeaderRateLimiter.observe."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("leaver.api.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("leaver.security.asyncio.sleep", fake_sleep)

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "9.0"},
                json={"retry_after": 0.5},
            )
        return httpx.Response(204)

    session = TokenSession(_dummy_token())
    client = DiscordClient(session, generate_fingerprint())
    client._http = httpx.AsyncClient(
        base_url="https://discord.com/api/v10",
        transport=httpx.MockTransport(handler),
    )
    try:
        res = await client.leave_guild(Guild("200", "Busy", owner=False, icon=None))
        assert res.status is LeaveStatus.LEFT
        assert len(sleeps) == 1
        assert client._limiter.total_waited == 0.0
    finally:
        await client.aclose()
        session.wipe()
