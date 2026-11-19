"""Module & PyInstaller entry point for Discord Server Leaver."""

from __future__ import annotations

import contextlib
import ctypes
import sys

from leaver.main import main

if __name__ == "__main__":
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetConsoleTitleW("Discord Server Leaver")
    try:
        main()
    except SystemExit as exc:
        if getattr(sys, "frozen", False) and sys.platform == "win32" and sys.stdin.isatty():
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input("\nPress Enter to exit...")
        raise exc
