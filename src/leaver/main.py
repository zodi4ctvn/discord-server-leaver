"""Entry point: wires the security, API and UI layers into the interactive flow."""

from __future__ import annotations

import asyncio
import os
import sys
import time

from dotenv import load_dotenv

from . import __author__, ui
from .api import APIError, DiscordClient, Guild, LeaveResult, User
from .i18n import detect_default_language, set_language, t
from .security import (
    TOKEN_ENV_VAR,
    SignatureError,
    TokenError,
    TokenRevokedError,
    TokenSession,
    acquire_token,
    clear_clipboard,
    clipboard_has_token,
    generate_fingerprint,
    verify_signature,
)
from .utils import GoBack, console, log_error, log_info, log_warning, next_delay

Fingerprint = tuple[str, str]


async def _login_and_fetch(
    session: TokenSession, fingerprint: Fingerprint
) -> tuple[User, list[Guild]]:
    """Steps 1-2: validate the token via ``/users/@me`` and fetch every guild."""
    async with DiscordClient(session, fingerprint) as client:
        with console.status(t("logging_in"), spinner="line"):
            user = await client.get_me()
        ui.show_logged_in(user)
        with console.status(t("fetching"), spinner="line"):
            guilds = await client.fetch_guilds()
    return user, guilds


async def _leave_all(
    session: TokenSession, fingerprint: Fingerprint, guilds: list[Guild]
) -> list[LeaveResult]:
    """Step 5: leave each guild sequentially with the adaptive human-like delay."""
    total = len(guilds)
    view = ui.LeaveProgressView(total)
    async with DiscordClient(session, fingerprint) as client:
        with view:
            for index, guild in enumerate(guilds, start=1):
                view.start(guild)
                result = await client.leave_guild(guild)  # 401 propagates → abort
                view.record(result)
                delay = next_delay(index, total)  # layer 2
                if delay > 0:
                    view.waiting(delay)
                    await asyncio.sleep(delay)
    return view.results


def _run(session: TokenSession, clients: list[str]) -> int:
    """Run steps 1-6 for an authenticated session and return the process exit code."""
    fingerprint = generate_fingerprint()  # rotated every run

    _, guilds = asyncio.run(_login_and_fetch(session, fingerprint))
    owned = [g for g in guilds if g.owner]
    admins = sum(1 for g in guilds if g.is_admin)
    staff = sum(1 for g in guilds if g.is_staff)
    ui.show_guild_count(len(guilds), len(owned), admins, staff)

    if len(guilds) == len(owned):
        log_info(t("no_leavable"))
        ui.show_summary([], len(owned), 0.0)
        return 0

    preselected: set[str] = set()
    while True:
        selected = ui.select_servers(guilds, preselected)
        if not selected:
            log_warning(t("sel_warning"))
            continue
        preselected = {g.id for g in selected}
        if ui.confirm_leave(selected, clients):
            break

    started = time.monotonic()
    results = asyncio.run(_leave_all(session, fingerprint, selected))
    elapsed = time.monotonic() - started
    ui.show_summary(results, len(owned), elapsed)
    return 0


def main() -> None:
    """CLI entry point (``dsl``)."""
    # DSL_TOKEN is only honoured if the user exported it in the real environment —
    # it is captured *before* any optional .env file is loaded, so a token is never
    # picked up from a file on disk.
    env_token_present = TOKEN_ENV_VAR in os.environ
    load_dotenv(override=False)
    if not env_token_present:
        os.environ.pop(TOKEN_ENV_VAR, None)

    session: TokenSession | None = None
    exit_code = 0
    try:
        verify_signature(__author__, ui._BANNER_LINES)
        set_language(detect_default_language())
        detected = ui.detect_clients()
        clients: list[str] = []
        step = 0
        while True:
            if step == 0:
                ui.clear_and_banner()
                ui.select_language()
                step = 1
            elif step == 1:
                ui.clear_and_banner()
                try:
                    clients = ui.select_clients(detected)
                    step = 2
                except GoBack:
                    step = 0
            elif step == 2:
                ui.clear_and_banner()
                while True:
                    try:
                        session = TokenSession(acquire_token())
                        step = 3
                        break
                    except GoBack:
                        step = 1 if detected else 0
                        break
                    except TokenError as exc:
                        log_error(str(exc))
            else:
                assert session is not None
                try:
                    exit_code = _run(session, clients)
                    break
                except GoBack:
                    session.wipe()
                    session = None
                    step = 2
    except KeyboardInterrupt:
        console.print(f"\n[yellow]{t('interrupted')}[/yellow]")
        exit_code = 130
    except SignatureError as exc:
        log_error(str(exc))
        exit_code = 1
    except TokenError as exc:
        log_error(str(exc))
        exit_code = 2
    except TokenRevokedError:
        log_error(t("err_401"))
        exit_code = 1
    except APIError as exc:
        log_error(str(exc))
        exit_code = 1
    except Exception as exc:  # last resort: no raw tracebacks, token still wiped below
        log_error(t("err_unexpected", name=type(exc).__name__, msg=exc))
        exit_code = 1
    finally:
        if session is not None:
            if session.active and sys.stdin.isatty() and clipboard_has_token(session.token):
                try:
                    if ui.ask_clear_clipboard() and clear_clipboard():
                        console.print(f"[dim]{t('clipboard_cleared')}[/dim]")
                except KeyboardInterrupt:
                    pass
            session.wipe()
            session = None
            console.print(f"[dim]{t('token_wiped')}[/dim]")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
