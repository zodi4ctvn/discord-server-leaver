"""All terminal UI: banner, client detection, server picker, confirmation, progress, summary."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import questionary
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent, merge_key_bindings
from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame
from rich import box
from rich.align import Align
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from . import __version__
from .api import Guild, LeaveResult, LeaveStatus, User
from .i18n import count_servers, detect_default_language, servers, set_language, t
from .security import _read_clipboard
from .utils import GoBack, console, estimate_seconds, format_duration

# --------------------------------------------------------------------------- #
# Step 0 — Banner (ANSI Shadow, Consolas-safe)
# --------------------------------------------------------------------------- #
_BANNER_LINES: tuple[str, ...] = (
    "███████╗ ██████╗ ██████╗ ██╗██╗  ██╗ ██████╗████████╗██╗   ██╗███╗   ██╗",
    "╚══███╔╝██╔═══██╗██╔══██╗██║██║  ██║██╔════╝╚══██╔══╝██║   ██║████╗  ██║",
    "  ███╔╝ ██║   ██║██║  ██║██║███████║██║        ██║   ██║   ██║██╔██╗ ██║",
    " ███╔╝  ██║   ██║██║  ██║██║╚════██║██║        ██║   ╚██╗ ██╔╝██║╚██╗██║",
    "███████╗╚██████╔╝██████╔╝██║     ██║╚██████╗   ██║    ╚████╔╝ ██║ ╚████║",
    "╚══════╝ ╚═════╝ ╚═════╝ ╚═╝     ╚═╝ ╚═════╝   ╚═╝     ╚═══╝  ╚═╝  ╚═══╝",
)

_BANNER_GRADIENT: tuple[str, ...] = (
    "#7b2cbf",
    "#9d4edd",
    "#b5179e",
    "#d90368",
    "#e040fb",
    "#ff00ff",
)


def show_banner() -> None:
    """Render the centered ANSI Shadow ``zodi4ctvn`` banner with neon gradient."""
    art = Text()
    for index, (line, color) in enumerate(zip(_BANNER_LINES, _BANNER_GRADIENT, strict=True)):
        art.append(line, style=f"bold {color}")
        if index < len(_BANNER_LINES) - 1:
            art.append("\n")

    subtitle = Text()
    subtitle.append("─────────  ", style="dim magenta")
    subtitle.append("Discord Server Leaver", style="bold bright_white")
    subtitle.append("  ·  ", style="dim")
    subtitle.append(t("version", v=__version__), style="bold bright_cyan")
    subtitle.append("  ─────────", style="dim magenta")

    console.print()
    console.print(Align.center(art))
    console.print(Align.center(subtitle))
    console.print()


def clear_and_banner() -> None:
    """Clear the terminal buffer completely and redraw the banner."""
    if sys.platform == "win32" and sys.stdout.isatty():
        os.system("cls")
    else:
        console.clear()
    show_banner()


#: Single-select style: only the currently highlighted (cursor) option is green.
_SELECT_STYLE = questionary.Style(
    [
        ("qmark", "fg:ansimagenta bold"),
        ("question", "bold"),
        ("instruction", "fg:ansibrightblack"),
        ("pointer", "fg:ansigreen bold"),
        ("highlighted", "fg:ansigreen bold noreverse"),
        ("selected", "fg:ansibrightblack noreverse"),
        ("text", "fg:ansibrightblack noreverse"),
        ("answer", "fg:ansigreen bold"),
    ]
)


def _attach_nav_keys(question: questionary.Question, *, allow_back: bool = False) -> None:
    """Add W/S navigation (for keyboards without arrow keys) and optional Backspace/Esc."""
    extra = KeyBindings()

    @extra.add("w")
    @extra.add("W")
    def _up(event: KeyPressEvent) -> None:
        event.app.key_processor.feed(KeyPress(Keys.Up), first=True)

    @extra.add("s")
    @extra.add("S")
    def _down(event: KeyPressEvent) -> None:
        event.app.key_processor.feed(KeyPress(Keys.Down), first=True)

    if allow_back:

        @extra.add("backspace")
        @extra.add("escape", eager=True)
        def _go_back(event: KeyPressEvent) -> None:
            event.app.exit(exception=GoBack())

    existing = question.application.key_bindings
    question.application.key_bindings = (
        merge_key_bindings([extra, existing]) if existing is not None else extra
    )


def select_language() -> str:
    """Ask the user to pick Turkish or English and activate the chosen language.

    Orders the OS-detected language first (or ``DSL_LANG`` if set) without setting
    ``default=``, so ``questionary`` only applies the ``highlighted`` style to whichever
    row the cursor is on.

    Raises:
        KeyboardInterrupt: If the user presses Ctrl+C.
    """
    tr_choice = questionary.Choice(title="Türkçe  (TR)", value="tr")
    en_choice = questionary.Choice(title="English (EN)", value="en")
    choices = (
        [tr_choice, en_choice] if detect_default_language() == "tr" else [en_choice, tr_choice]
    )
    question = questionary.select(
        t("lang_prompt"),
        choices=choices,
        instruction="(↑↓ / W·S · Enter)",
        style=_SELECT_STYLE,
    )
    _attach_nav_keys(question, allow_back=False)
    selected: str = question.unsafe_ask()
    set_language(selected)
    return selected


# --------------------------------------------------------------------------- #
# Discord client detection (cosmetic / informational only)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class DetectedClient:
    """An installed Discord desktop client."""

    key: str
    label: str
    location: str


#: (internal key, display label, macOS app bundle, Linux binary, Linux config dir, flatpak id)
_CLIENT_SPECS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("Discord", "Stable", "Discord.app", "discord", "discord", "com.discordapp.Discord"),
    (
        "DiscordCanary",
        "Canary",
        "Discord Canary.app",
        "discord-canary",
        "discordcanary",
        "com.discordapp.DiscordCanary",
    ),
    (
        "DiscordPTB",
        "PTB",
        "Discord PTB.app",
        "discord-ptb",
        "discordptb",
        "com.discordapp.DiscordPTB",
    ),
)


def _detect_windows(key: str) -> str | None:
    """Look up a Discord client in the Windows registry, then in ``%LOCALAPPDATA%``."""
    if sys.platform == "win32":
        import winreg

        subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{key}"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, subkey) as handle:
                    for value_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                        try:
                            value, _ = winreg.QueryValueEx(handle, value_name)
                        except OSError:
                            continue
                        if value:
                            return str(value).strip('"')
                    return f"registry:{subkey}"
            except OSError:
                continue
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / key
        if (candidate / "Update.exe").exists() or candidate.is_dir():
            return str(candidate)
    return None


def _detect_macos(bundle: str) -> str | None:
    """Look for a Discord ``.app`` bundle in the system and user Applications folders."""
    for root in (Path("/Applications"), Path.home() / "Applications"):
        candidate = root / bundle
        if candidate.exists():
            return str(candidate)
    return None


def _detect_linux(binary: str, config_dir: str, flatpak_id: str) -> str | None:
    """Look for a Discord client binary, install dir, flatpak or config dir on Linux."""
    found = shutil.which(binary)
    if found:
        return found
    candidates = [
        Path("/opt") / binary,
        Path("/usr/share") / binary,
        Path("/usr/lib") / binary,
        Path("/var/lib/flatpak/app") / flatpak_id,
        Path.home() / ".local/share/flatpak/app" / flatpak_id,
        Path("/snap") / binary,
        Path.home() / ".config" / config_dir,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def detect_clients() -> list[DetectedClient]:
    """Detect installed Discord Stable / Canary / PTB clients on the current OS."""
    detected: list[DetectedClient] = []
    for key, label, bundle, binary, config_dir, flatpak_id in _CLIENT_SPECS:
        if sys.platform == "win32":
            location = _detect_windows(key)
        elif sys.platform == "darwin":
            location = _detect_macos(bundle)
        else:
            location = _detect_linux(binary, config_dir, flatpak_id)
        if location:
            detected.append(DetectedClient(key=key, label=label, location=location))
    return detected


def select_clients(detected: list[DetectedClient]) -> list[str]:
    """Let the user pick which detected client profile(s) to target using arrow keys.

    The choice is purely informational and only appears in the confirmation summary.

    Returns:
        The selected client labels (e.g. ``["Stable"]`` or ``["Stable", "Canary"]``);
        empty in token-only mode.

    Raises:
        GoBack: If the user presses Backspace or Esc.
        KeyboardInterrupt: If the user presses Ctrl+C.
    """
    if not detected:
        console.print(f"[yellow]{t('no_client')}[/yellow]")
        return []

    choices: list[questionary.Choice] = [
        questionary.Choice(title=f"{c.label}  ({c.location})", value=[c.label]) for c in detected
    ]

    question = questionary.select(
        t("client_prompt"),
        choices=choices,
        instruction=t("client_instruction"),
        style=_SELECT_STYLE,
    )
    _attach_nav_keys(question, allow_back=True)
    selected: list[str] = question.unsafe_ask()
    return selected


def describe_clients(labels: list[str]) -> str:
    """Return a human-readable client description, e.g. ``Stable + Canary``."""
    return " + ".join(labels) if labels else t("token_only")


# --------------------------------------------------------------------------- #
# Step 1 / 2 — login + fetch feedback
# --------------------------------------------------------------------------- #
def show_logged_in(user: User) -> None:
    """Print the ``+ Logged in as ...`` line."""
    line = Text("+ ", style="bold green")
    line.append(t("logged_in"), style="green")
    line.append(user.tag, style="bold bright_white")
    line.append(f"  (ID: {user.id})", style="dim cyan")
    console.print(line)


def show_guild_count(count: int, owned: int, admin: int = 0, staff: int = 0) -> None:
    """Print how many servers were found along with owner / admin / staff counts."""
    console.print(t("found_servers", count=count, noun=servers(count)))
    if owned or admin or staff:
        console.print(t("role_breakdown", owned=owned, admin=admin, staff=staff))


# --------------------------------------------------------------------------- #
# Step 3 — Two-panel server selection
# --------------------------------------------------------------------------- #
_SELECTOR_STYLE = Style.from_dict(
    {
        "title": "bg:#5865f2 fg:#ffffff bold",
        "cursor": "bg:#2b2d31 fg:#00d1ff bold",
        "checked": "fg:#57f287 bold",
        "unchecked": "fg:#6d6f78",
        "owner": "fg:#ed4245 bold",
        "admin": "fg:#fee75c bold",
        "staff": "fg:#00d1ff bold",
        "locked": "fg:#6d6f78",
        "muted": "fg:#80848e",
        "stat": "fg:#ffffff bold",
        "toolbar": "bg:#1e1f22 fg:#b5bac1",
        "key": "bg:#1e1f22 fg:#00d1ff bold",
        "warning": "bg:#fee75c fg:#1e1f22 bold",
        "frame.border": "fg:#5865f2",
        "frame.label": "fg:#eb459e bold",
    }
)


class ServerSelector:
    """Full-screen two-panel picker: checkbox list on the left, live search on the right.

    Built directly on ``prompt_toolkit`` (the engine behind ``questionary``) because a
    stock ``questionary.checkbox`` cannot be filtered live from a second panel.
    """

    def __init__(self, guilds: list[Guild], preselected: set[str] | None = None) -> None:
        """Create a selector for ``guilds`` (sorted A-Z internally)."""
        self.guilds = sorted(guilds, key=lambda g: (g.name.casefold(), g.id))
        self.selected: set[str] = {
            gid
            for gid in (preselected or set())
            if any(g.id == gid and not g.owner for g in guilds)
        }
        self.cursor = 0
        self.warning: str = ""
        self.search = Buffer(multiline=False, on_text_changed=self._on_search_changed)
        self.list_window = Window(
            FormattedTextControl(
                self._list_fragments,
                focusable=True,
                show_cursor=False,
                get_cursor_position=lambda: Point(x=0, y=self.cursor),
            ),
            wrap_lines=False,
        )
        self.app: Application[list[Guild]] = Application(
            layout=Layout(self._build_root(), focused_element=self.list_window),
            key_bindings=self._build_keys(),
            style=_SELECTOR_STYLE,
            full_screen=True,
            mouse_support=False,
        )

    # ------------------------------------------------------------------ data
    def visible(self) -> list[Guild]:
        """Return the guilds matching the current search text."""
        query = self.search.text.strip().casefold()
        if not query:
            return self.guilds
        return [g for g in self.guilds if query in g.name.casefold()]

    def _on_search_changed(self, _: Buffer) -> None:
        """Reset the cursor whenever the filter changes."""
        self.cursor = 0

    def _clamp(self, count: int) -> None:
        """Keep the cursor inside ``[0, count)``."""
        self.cursor = max(0, min(self.cursor, count - 1)) if count else 0

    # ------------------------------------------------------------------ rendering
    def _list_fragments(self) -> StyleAndTextTuples:
        """Render the checkbox list."""
        items = self.visible()
        self._clamp(len(items))
        if not items:
            return [("class:muted", f"{t('sel_no_match')}\n")]
        out: StyleAndTextTuples = []
        owner_badge = t("owner_badge")
        admin_badge = t("admin_badge")
        staff_badge = t("staff_badge")
        for index, guild in enumerate(items):
            on_cursor = index == self.cursor
            prefix = "class:cursor " if on_cursor else ""
            pointer = "» " if on_cursor else "  "
            if guild.owner:
                out.append((prefix + "class:locked", f"{pointer}× {guild.name} "))
                out.append((prefix + "class:owner", owner_badge))
            else:
                if guild.id in self.selected:
                    out.append((prefix + "class:checked", f"{pointer}● "))
                else:
                    out.append((prefix + "class:unchecked", f"{pointer}○ "))
                out.append((prefix.strip(), guild.name))
                if guild.is_admin:
                    out.append((prefix + "class:admin", f" {admin_badge}"))
                elif guild.is_staff:
                    out.append((prefix + "class:staff", f" {staff_badge}"))
            out.append(("", "\n"))
        return out

    def _stats_fragments(self) -> StyleAndTextTuples:
        """Render the statistics / selection preview under the search box."""
        items = self.visible()
        owned = sum(1 for g in self.guilds if g.owner)
        admins = sum(1 for g in self.guilds if g.is_admin)
        staff = sum(1 for g in self.guilds if g.is_staff)
        out: StyleAndTextTuples = [
            ("", t("stat_matching")),
            ("class:stat", f"{len(items)} / {len(self.guilds)}\n"),
            ("", t("stat_selected")),
            ("class:checked", f"{len(self.selected)}\n"),
            ("", t("stat_owned")),
            ("class:owner", f"{owned}"),
            ("class:muted", f"{t('stat_locked')}\n"),
            ("", t("stat_admin")),
            ("class:admin", f"{admins}\n"),
            ("", t("stat_staff")),
            ("class:staff", f"{staff}\n\n"),
        ]
        names = [g.name for g in self.guilds if g.id in self.selected]
        if names:
            out.append(("class:stat", f"{t('stat_will_leave')}\n"))
            for name in names[:15]:
                out.append(("", f"  • {name}\n"))
            if len(names) > 15:
                out.append(("class:muted", f"{t('stat_more', n=len(names) - 15)}\n"))
        else:
            out.append(("class:muted", f"{t('stat_nothing')}\n"))
        return out

    def _toolbar_fragments(self) -> StyleAndTextTuples:
        """Render the keyboard-shortcut bar (or a pending warning)."""
        if self.warning:
            return [("class:warning", f" {self.warning}")]
        pairs = (
            (t("key_space"), t("key_toggle")),
            ("A", t("key_select_all")),
            ("U", t("key_select_regular")),
            ("N", t("key_deselect_all")),
            ("/", t("key_search")),
            ("↑↓/WS", t("key_move")),
            ("Enter", t("key_confirm")),
            ("Backspace", t("key_back")),
            ("Ctrl+C", t("key_quit")),
        )
        out: StyleAndTextTuples = []
        for key, label in pairs:
            out.append(("class:key", f" {key}"))
            out.append(("class:toolbar", f" = {label}  "))
        return out

    def _build_root(self) -> HSplit:
        """Assemble the two-panel layout."""
        title = Window(
            FormattedTextControl([("class:title", t("sel_title"))]),
            height=1,
        )
        left = Frame(self.list_window, title=t("frame_servers"))
        right = HSplit(
            [
                Frame(Window(BufferControl(self.search), height=1), title=t("frame_search")),
                Frame(
                    Window(FormattedTextControl(self._stats_fragments), wrap_lines=True),
                    title=t("frame_selection"),
                ),
            ]
        )
        body = VSplit(
            [
                HSplit([left], width=Dimension(weight=3)),
                HSplit([right], width=Dimension(weight=2)),
            ]
        )
        toolbar = Window(
            FormattedTextControl(self._toolbar_fragments), height=1, style="class:toolbar"
        )
        return HSplit([title, body, toolbar])

    # ------------------------------------------------------------------ keys
    def _build_keys(self) -> KeyBindings:
        """Create the key bindings for list and search focus modes."""
        kb = KeyBindings()
        in_list = has_focus(self.list_window)
        in_search = has_focus(self.search)

        @kb.add("c-c")
        def _quit(event: KeyPressEvent) -> None:
            event.app.exit(exception=KeyboardInterrupt())

        @kb.add("backspace", filter=in_list)
        @kb.add("escape", filter=in_list, eager=True)
        def _go_back(event: KeyPressEvent) -> None:
            event.app.exit(exception=GoBack())

        @kb.add("up", filter=in_list)
        @kb.add("w", filter=in_list)
        @kb.add("W", filter=in_list)
        @kb.add("k", filter=in_list)
        def _up(event: KeyPressEvent) -> None:
            self.cursor = max(0, self.cursor - 1)

        @kb.add("down", filter=in_list)
        @kb.add("s", filter=in_list)
        @kb.add("S", filter=in_list)
        @kb.add("j", filter=in_list)
        def _down(event: KeyPressEvent) -> None:
            self.cursor = min(len(self.visible()) - 1, self.cursor + 1)
            self._clamp(len(self.visible()))

        @kb.add("pageup", filter=in_list)
        def _page_up(event: KeyPressEvent) -> None:
            self.cursor = max(0, self.cursor - 10)

        @kb.add("pagedown", filter=in_list)
        def _page_down(event: KeyPressEvent) -> None:
            self.cursor = min(len(self.visible()) - 1, self.cursor + 10)
            self._clamp(len(self.visible()))

        @kb.add("home", filter=in_list)
        def _home(event: KeyPressEvent) -> None:
            self.cursor = 0

        @kb.add("end", filter=in_list)
        def _end(event: KeyPressEvent) -> None:
            self.cursor = max(0, len(self.visible()) - 1)

        @kb.add("space", filter=in_list)
        def _toggle(event: KeyPressEvent) -> None:
            items = self.visible()
            if not items:
                return
            guild = items[self.cursor]
            if guild.owner:
                return
            self.warning = ""
            self.selected.symmetric_difference_update({guild.id})

        @kb.add("a", filter=in_list)
        @kb.add("A", filter=in_list)
        def _select_all(event: KeyPressEvent) -> None:
            self.warning = ""
            self.selected.update(g.id for g in self.visible() if not g.owner)

        @kb.add("u", filter=in_list)
        @kb.add("U", filter=in_list)
        def _select_regular(event: KeyPressEvent) -> None:
            self.warning = ""
            visible_ids = {g.id for g in self.visible()}
            self.selected.difference_update(visible_ids)
            self.selected.update(
                g.id for g in self.visible() if not g.owner and not g.is_admin and not g.is_staff
            )

        @kb.add("n", filter=in_list)
        @kb.add("N", filter=in_list)
        def _deselect_all(event: KeyPressEvent) -> None:
            self.selected.difference_update(g.id for g in self.visible())

        @kb.add("/", filter=in_list)
        @kb.add("tab", filter=in_list)
        def _focus_search(event: KeyPressEvent) -> None:
            event.app.layout.focus(self.search)

        @kb.add("enter", filter=in_search)
        @kb.add("escape", filter=in_search, eager=True)
        @kb.add("down", filter=in_search)
        @kb.add("tab", filter=in_search)
        def _focus_list(event: KeyPressEvent) -> None:
            event.app.layout.focus(self.list_window)

        @kb.add("enter", filter=in_list)
        def _confirm(event: KeyPressEvent) -> None:
            if not self.selected:
                self.warning = t("sel_warning")
                return
            event.app.exit(result=[g for g in self.guilds if g.id in self.selected])

        return kb

    def run(self) -> list[Guild]:
        """Run the picker and return the selected (non-owned) guilds, sorted A-Z."""
        return self.app.run()


def select_servers(guilds: list[Guild], preselected: set[str] | None = None) -> list[Guild]:
    """Show the two-panel picker and return the guilds the user chose to leave.

    Raises:
        KeyboardInterrupt: If the user presses Ctrl+C.
    """
    return ServerSelector(guilds, preselected).run()


# --------------------------------------------------------------------------- #
# Step 4 — Confirmation
# --------------------------------------------------------------------------- #
def _estimate_text(count: int) -> str:
    """Return e.g. ``~45 seconds`` or ``~3m 12s``."""
    seconds = estimate_seconds(count)
    if seconds < 60:
        return t("est_seconds", n=max(1, round(seconds)))
    return f"~{format_duration(seconds)}"


_TEXT_PROMPT_STYLE = questionary.Style(
    [
        ("qmark", "fg:ansimagenta bold"),
        ("question", "bold"),
        ("answer", "fg:ansigreen"),
    ]
)


def _prompt_text_with_back(message: str) -> str:
    """Read text with ``Ctrl+V`` paste and ``Backspace`` (when empty) / ``Esc`` to go back."""
    if not sys.stdin.isatty():
        return Prompt.ask(
            f"[bold bright_magenta]?[/bold bright_magenta] [bold]{message}[/bold]",
            default="",
            show_default=False,
            console=console,
        ).strip()

    question = questionary.text(message, style=_TEXT_PROMPT_STYLE)
    extra = KeyBindings()
    buf_empty = Condition(lambda: len(question.application.current_buffer.text) == 0)

    @extra.add("c-v")
    def _paste(event: KeyPressEvent) -> None:
        text = _read_clipboard().strip()
        if text:
            event.current_buffer.insert_text(text)

    @extra.add("backspace", filter=buf_empty)
    @extra.add("escape", eager=True)
    def _go_back(event: KeyPressEvent) -> None:
        event.app.exit(exception=GoBack())

    existing = question.application.key_bindings
    question.application.key_bindings = (
        merge_key_bindings([extra, existing]) if existing is not None else extra
    )
    value: str = question.unsafe_ask()
    return value.strip()


def confirm_leave(selected: list[Guild], clients: list[str]) -> bool:
    """Show the confirmation panel and require typing ``CONFIRM`` or ``ONAYLA``.

    Returns:
        ``True`` only if the user typed ``CONFIRM`` or ``ONAYLA``.
    """
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(no_wrap=False)
    table.add_row(Text(t("confirm_title"), style="bold bright_red"))
    table.add_row("")
    table.add_row(t("confirm_count", n=len(selected), noun=servers(len(selected))))
    table.add_row(t("confirm_client", clients=describe_clients(clients)))
    table.add_row(t("confirm_eta", eta=_estimate_text(len(selected))))
    table.add_row("")
    table.add_row(Text(t("confirm_servers"), style="bold bright_white"))
    for idx, guild in enumerate(selected, start=1):
        row = Text(f"  {idx:>2}. ", style="dim red")
        row.append(guild.name, style="white")
        if guild.is_admin:
            row.append(f"  {t('admin_badge')}", style="bold yellow")
        elif guild.is_staff:
            row.append(f"  {t('staff_badge')}", style="bold cyan")
        table.add_row(row)

    console.print()
    console.print(
        Panel(
            table,
            title=f"[bold bright_red]{t('confirm_panel_title')}[/bold bright_red]",
            box=box.DOUBLE,
            border_style="bright_red",
            padding=(1, 2),
            expand=False,
        )
    )

    try:
        answer = _prompt_text_with_back(t("confirm_prompt"))
    except GoBack:
        return False
    return answer in (t("confirm_keyword"), "CONFIRM", "ONAYLA")


# --------------------------------------------------------------------------- #
# Step 5 — Execution view
# --------------------------------------------------------------------------- #
def _status_label(status: LeaveStatus) -> tuple[str, str]:
    """Return the localized ``(label, rich_style)`` pair for ``status``."""
    if status is LeaveStatus.LEFT:
        return t("status_left"), "bold green"
    if status is LeaveStatus.SKIPPED:
        return t("status_skipped"), "bold yellow"
    return t("status_error"), "bold red"


class LeaveProgressView:
    """Flicker-free progress bar + permanent log of every left server.

    Each completed server is printed permanently above the single-line progress bar so:
    - Classic Windows CMD does not flicker (only one line redraws).
    - Earlier servers are never hidden — every single server remains visible.
    """

    def __init__(self, total: int) -> None:
        """Create the view for ``total`` leave operations."""
        self.total = total
        self.results: list[LeaveResult] = []
        self.progress = Progress(
            SpinnerColumn(spinner_name="line", style="bright_magenta"),
            TextColumn("\\[{task.completed:.0f}/{task.total:.0f}]", style="bold bright_cyan"),
            BarColumn(
                bar_width=32,
                style="dim white",
                complete_style="bright_magenta",
                finished_style="bold green",
            ),
            TextColumn("{task.fields[current]}", style="bold white"),
            TextColumn("{task.fields[status]}"),
            TextColumn(t("eta"), style="dim"),
            TimeRemainingColumn(),
            console=console,
            expand=False,
        )
        self.task: TaskID = self.progress.add_task("leave", total=total, current="", status="")
        self._live = Live(self.progress, console=console, refresh_per_second=4, transient=True)

    @staticmethod
    def _short(name: str, width: int = 32) -> str:
        """Truncate and markup-escape a server name for the progress line."""
        clipped = name if len(name) <= width else name[: width - 1] + "…"
        return clipped.replace("[", "\\[")

    def start(self, guild: Guild) -> None:
        """Mark ``guild`` as the server currently being left."""
        self.progress.update(
            self.task, current=self._short(guild.name), status=f"[cyan]{t('status_leaving')}[/cyan]"
        )

    def record(self, result: LeaveResult) -> None:
        """Print the finished server permanently above the bar and advance progress."""
        self.results.append(result)
        index = len(self.results)
        label, style = _status_label(result.status)

        row = Text()
        row.append(f"  {index:>3}. ", style="dim cyan")
        row.append(f"{label:<11} ", style=style)
        row.append(result.guild.name, style="white")
        if result.status is not LeaveStatus.LEFT and result.detail:
            row.append(f"  — {result.detail}", style="dim")
        self._live.console.print(row)

        self.progress.update(self.task, advance=1, status=f"[{style}]{label}[/{style}]")

    def waiting(self, seconds: float) -> None:
        """Show that the tool is pausing (human-like delay) before the next request."""
        if seconds <= 0:
            return
        self.progress.update(
            self.task, status=f"[dim]{t('status_waiting', s=f'{seconds:.1f}')}[/dim]"
        )

    def __enter__(self) -> LeaveProgressView:
        """Print the section header and start the single-line Live progress bar."""
        console.print()
        console.print(f"[bold bright_magenta]── {t('exec_title')} ──[/bold bright_magenta]")
        self._live.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the Live display cleanly."""
        self.progress.update(self.task, current="", status="")
        self._live.stop()


# --------------------------------------------------------------------------- #
# Step 6 — Summary
# --------------------------------------------------------------------------- #
def show_summary(results: list[LeaveResult], owned_count: int, elapsed: float) -> None:
    """Render the final summary panel.

    Args:
        results: Every leave result produced in this run.
        owned_count: Number of servers the user owns (always skipped).
        elapsed: Wall-clock duration of the leave phase, in seconds.
    """
    left = sum(1 for r in results if r.status is LeaveStatus.LEFT)
    owner_skips = owned_count + sum(1 for r in results if r.owner_skip)
    other_skips = [r for r in results if r.status is LeaveStatus.SKIPPED and not r.owner_skip]
    errors = [r for r in results if r.status is LeaveStatus.ERROR]

    grid = Table(box=None, show_header=False, padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column(justify="right")
    grid.add_row(
        Text(t("sum_left"), style="bold green"), Text(count_servers(left), style="bold green")
    )
    grid.add_row(
        Text(t("sum_skipped_owner"), style="yellow"),
        Text(count_servers(owner_skips), style="bold yellow"),
    )
    if other_skips:
        grid.add_row(
            Text(t("sum_skipped_forbidden"), style="yellow"),
            Text(count_servers(len(other_skips)), style="bold yellow"),
        )
    err_style = "bold red" if errors else "dim"
    grid.add_row(Text(t("sum_errors"), style=err_style), Text(str(len(errors)), style=err_style))
    grid.add_row(
        Text(t("sum_time"), style="cyan"),
        Text(format_duration(elapsed), style="bold bright_cyan"),
    )

    border = "bright_green" if not errors else "yellow"
    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold {border}]{t('sum_title')}[/bold {border}]",
            box=box.DOUBLE,
            border_style=border,
            expand=False,
            padding=(1, 2),
        )
    )

    if owner_skips:
        console.print(f"[dim]{t('sum_owned_note', s=count_servers(owner_skips))}[/dim]")
    for result in [*other_skips, *errors]:
        label, style = _status_label(result.status)
        line = Text(f"{label}: ", style=style)
        line.append(result.guild.name, style="bold")
        line.append(f" — {result.detail}", style="dim")
        console.print(line)


def ask_clear_clipboard() -> bool:
    """Optionally ask the user whether to clear their clipboard before exiting."""
    question = questionary.select(
        t("clipboard_prompt"),
        choices=[
            questionary.Choice(title=t("clipboard_yes"), value=True),
            questionary.Choice(title=t("clipboard_no"), value=False),
        ],
        instruction="(↑↓ / W·S · Enter)",
        style=_SELECT_STYLE,
    )
    _attach_nav_keys(question, allow_back=False)
    answer: bool = question.unsafe_ask()
    return answer
