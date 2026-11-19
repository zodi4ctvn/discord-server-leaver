"""Brand & attribution integrity guard for Discord Server Leaver (Zodi4c / zodi4ctvn)."""

from __future__ import annotations

import sys
from pathlib import Path

from rich import box
from rich.panel import Panel
from rich.text import Text

from . import __author__, ui
from .i18n import STRINGS
from .security import SignatureError, verify_signature
from .utils import console

EXPECTED_AUTHOR: str = "zodi4ctvn"
EXPECTED_BRAND: str = "Zodi4c"
EXPECTED_GITHUB_URL: str = "https://github.com/zodi4ctvn"
EXPECTED_PROJECT_NAME: str = "Discord Server Leaver"
EXPECTED_PACKAGE_NAME: str = "leaver"
EXPECTED_REPO_URL: str = "https://github.com/zodi4ctvn/discord-server-leaver"


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def check_integrity(
    *,
    author: str | None = None,
    banner_lines: tuple[str, ...] | None = None,
    package_name: str | None = None,
    strings: dict[str, dict[str, str]] | None = None,
    repo_root: Path | None = None,
    is_frozen: bool | None = None,
) -> list[str]:
    """Return a list of integrity violations (empty when attribution & branding are intact)."""
    violations: list[str] = []

    actual_author = __author__ if author is None else author
    actual_banner = ui._BANNER_LINES if banner_lines is None else banner_lines
    actual_package = (__package__ or "") if package_name is None else package_name
    actual_strings = STRINGS if strings is None else strings
    frozen = bool(getattr(sys, "frozen", False)) if is_frozen is None else is_frozen

    # 1. Runtime checks (always run — both source and PyInstaller frozen builds)
    if actual_author != EXPECTED_AUTHOR:
        violations.append("author_mismatch")

    try:
        verify_signature(actual_author, actual_banner)
    except SignatureError:
        violations.append("banner_signature_mismatch")

    if actual_package != EXPECTED_PACKAGE_NAME:
        violations.append("package_renamed")

    for lang in ("en", "tr"):
        sel_title = actual_strings.get(lang, {}).get("sel_title", "")
        if EXPECTED_PROJECT_NAME not in sel_title:
            violations.append(f"i18n_project_name_missing:{lang}")

    # 2. Source-tree checks (only when running from unbundled source)
    if not frozen:
        pkg_dir = Path(__file__).resolve().parent
        ui_file = pkg_dir / "ui.py"
        if ui_file.is_file():
            ui_src = _read_text_safe(ui_file)
            if EXPECTED_PROJECT_NAME not in ui_src:
                violations.append("ui_project_name_missing")

        root = repo_root if repo_root is not None else pkg_dir.parent.parent
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            pyproject_txt = _read_text_safe(pyproject)
            if EXPECTED_AUTHOR not in pyproject_txt or EXPECTED_REPO_URL not in pyproject_txt:
                violations.append("pyproject_attribution_missing")

            license_file = root / "LICENSE"
            if license_file.is_file():
                license_txt = _read_text_safe(license_file)
                if EXPECTED_BRAND not in license_txt or EXPECTED_GITHUB_URL not in license_txt:
                    violations.append("license_attribution_missing")

            readme_file = root / "README.md"
            if readme_file.is_file():
                readme_txt = _read_text_safe(readme_file)
                if EXPECTED_AUTHOR not in readme_txt or EXPECTED_PROJECT_NAME not in readme_txt:
                    violations.append("readme_attribution_missing")

    return violations


def _render_tamper_panel() -> Panel:
    body = Text()
    body.append("TR — BÜTÜNLÜK VE ATIF HATASI\n", style="bold bright_red")
    body.append(
        f"Bu aracın orijinal adı ({EXPECTED_PROJECT_NAME}) veya geliştirici atfı "
        f"({EXPECTED_BRAND} / {EXPECTED_AUTHOR}) değiştirilmiş ya da kaldırılmış.\n"
        f"Lütfen orijinal proje adını ve geliştirici atfını geri yükleyin:\n",
        style="white",
    )
    body.append(f"  {EXPECTED_GITHUB_URL}\n\n", style="bold bright_cyan")
    body.append("EN — INTEGRITY & ATTRIBUTION ERROR\n", style="bold bright_red")
    body.append(
        f"The original project name ({EXPECTED_PROJECT_NAME}) or author attribution "
        f"({EXPECTED_BRAND} / {EXPECTED_AUTHOR}) has been modified or removed.\n"
        f"Please restore the original project name and author attribution:\n",
        style="white",
    )
    body.append(f"  {EXPECTED_GITHUB_URL}", style="bold bright_cyan")

    return Panel(
        body,
        title="[bold bright_red]! INTEGRITY CHECK FAILED / BÜTÜNLÜK HATASI[/bold bright_red]",
        box=box.DOUBLE,
        border_style="bright_red",
        padding=(1, 2),
        expand=False,
    )


def verify_integrity() -> None:
    """Verify brand & author attribution; display a red TR+EN error panel and exit on tampering."""
    if check_integrity():
        console.print()
        console.print(_render_tamper_panel())
        console.print()
        sys.exit(1)
