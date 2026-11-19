"""Tiny i18n layer: Turkish and English UI strings."""

from __future__ import annotations

import locale
import os
from typing import Any

SUPPORTED: tuple[str, ...] = ("tr", "en")
_current: str = "en"

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # banner / language
        "version": "v{v}",
        "lang_prompt": "Dil / Language:",
        # client detection
        "no_client": "! No Discord desktop client detected. Continuing in token-only mode.",
        "client_prompt": "Select the Discord client to target:",
        "client_instruction": "(↑↓ / W·S · Enter = select · Backspace = back)",
        "token_only": "Token-only",
        # token
        "env_warning": (
            "! Using token from the {var} environment variable. This is insecure: "
            "environment variables can leak via shell history, process listings and crash dumps."
        ),
        "token_prompt": "Enter your Discord token (masked · Esc/Backspace = back):",
        "err_token_format": "Invalid token format. Refusing to contact Discord.",
        # login / fetch
        "logging_in": "Authenticating with Discord...",
        "logged_in": "Logged in as ",
        "fetching": "Fetching your servers...",
        "found_servers": "• Found [bold bright_cyan]{count}[/bold bright_cyan] {noun}",
        "role_breakdown": "  [red]Owner: {owned}[/red]  ·  [yellow]Admin: {admin}[/yellow]  ·  [cyan]Mod/Staff: {staff}[/cyan]",
        "no_leavable": "There are no servers you can leave.",
        # selector
        "sel_title": " Discord Server Leaver — Select servers to leave ",
        "sel_no_match": "  No servers match your search.",
        "owner_badge": "[OWNER]",
        "admin_badge": "[ADMIN]",
        "staff_badge": "[MOD]",
        "stat_matching": " • Matching:  ",
        "stat_selected": " + Selected:  ",
        "stat_owned": " * Owned:     ",
        "stat_admin": " ! Admin:     ",
        "stat_staff": " + Mod/Staff: ",
        "stat_locked": " (locked)",
        "stat_will_leave": " » Will leave:",
        "stat_more": "  … and {n} more",
        "stat_nothing": " Nothing selected yet.",
        "key_space": "Space",
        "key_toggle": "toggle",
        "key_select_all": "select all",
        "key_select_regular": "regular only",
        "key_deselect_all": "clear",
        "key_search": "search",
        "key_move": "move",
        "key_confirm": "confirm",
        "key_back": "back",
        "key_quit": "quit",
        "frame_servers": " Servers (A-Z) ",
        "frame_search": " Search  ( / ) ",
        "frame_selection": " Selection ",
        "sel_warning": "! You did not select any servers — select at least one!",
        # confirmation
        "confirm_panel_title": "! CONFIRMATION REQUIRED",
        "confirm_title": "» You are about to LEAVE:",
        "confirm_count": "• Servers:        [bold bright_red]{n}[/bold bright_red] {noun}",
        "confirm_client": "• Client:         [bold cyan]{clients}[/bold cyan]",
        "confirm_eta": "• Estimated time: [bold yellow]{eta}[/bold yellow]",
        "confirm_servers": "» Selected servers:",
        "confirm_prompt": (
            "[bold]» Type [bold bright_red]CONFIRM[/bold bright_red] to proceed, "
            "or press [dim]Enter[/dim] to go back[/bold]"
        ),
        "est_seconds": "~{n} seconds",
        "cancelled": "× Cancelled. No servers were left.",
        "going_back": "« Going back...",
        # execution
        "exec_title": "Leaving Servers",
        "status_left": "+ Left",
        "status_skipped": "! Skipped",
        "status_error": "× Error",
        "status_leaving": "» Leaving...",
        "status_waiting": "… Human delay {s}s",
        "eta": "ETA",
        "col_server": "Server",
        "col_status": "Status",
        "col_detail": "Detail",
        "hidden_rows": "… {n} earlier result(s) hidden",
        # api details / errors
        "detail_left": "Left",
        "detail_owner": "Owner",
        "detail_forbidden": "Cannot leave {name} (forbidden)",
        "detail_404": "Unknown server (404)",
        "detail_unexpected": "Unexpected status {status}",
        "err_network": "Network error: {name}",
        "err_429": "Rate limited too many times (429).",
        "err_5xx": "Discord server error ({status}).",
        "err_account": "Could not fetch account ({status}).",
        "err_bot": "Bot accounts are not supported — use a user account token.",
        "err_guilds": "Could not fetch servers ({status}).",
        "err_401": "Token is invalid or has been revoked (HTTP 401). Aborting.",
        "err_unexpected": "Unexpected error: {name}: {msg}",
        # summary
        "sum_title": "Summary",
        "sum_left": "+ Left:",
        "sum_skipped_owner": "* Skipped (owner):",
        "sum_skipped_forbidden": "! Skipped (forbidden):",
        "sum_errors": "× Errors:",
        "sum_time": "• Total time:",
        "sum_owned_note": "* You own {s}, skipped.",
        # exit
        "interrupted": "! Interrupted. Cleaning up...",
        "token_wiped": "+ Token securely wiped from memory.",
        "clipboard_prompt": "Token is still in your clipboard — clear it now?",
        "clipboard_yes": "Yes — clear clipboard",
        "clipboard_no": "No — keep it",
        "clipboard_cleared": "+ Clipboard cleared.",
    },
    "tr": {
        "version": "v{v}",
        "lang_prompt": "Dil / Language:",
        "no_client": "! Discord masaüstü uygulaması bulunamadı. Sadece token ile devam ediliyor.",
        "client_prompt": "Hedeflenecek Discord uygulamasını seç:",
        "client_instruction": "(↑↓ / W·S · Enter = seç · Backspace = geri)",
        "token_only": "Sadece token",
        "env_warning": (
            "! Token {var} ortam değişkeninden alınıyor. Bu güvensizdir: ortam değişkenleri "
            "komut geçmişi, işlem listeleri ve hata dökümleri yoluyla sızabilir."
        ),
        "token_prompt": "Discord token'ını yapıştır (yıldızlı · Esc/Backspace = geri):",
        "err_token_format": "Geçersiz token formatı. Discord'a bağlanılmadı.",
        "logging_in": "Discord'a giriş yapılıyor...",
        "logged_in": "Giriş yapıldı: ",
        "fetching": "Sunucuların getiriliyor...",
        "found_servers": "• Toplam [bold bright_cyan]{count}[/bold bright_cyan] {noun} bulundu",
        "role_breakdown": "  [red]Sahibi: {owned}[/red]  ·  [yellow]Yönetici: {admin}[/yellow]  ·  [cyan]Yetkili: {staff}[/cyan]",
        "no_leavable": "Ayrılabileceğin bir sunucu yok.",
        "sel_title": " Discord Server Leaver — Ayrılmak istediğin sunucuları seç ",
        "sel_no_match": "  Aramana uyan sunucu yok.",
        "owner_badge": "[SAHİBİ]",
        "admin_badge": "[YÖNETİCİ]",
        "staff_badge": "[YETKİLİ]",
        "stat_matching": " • Eşleşen:   ",
        "stat_selected": " + Seçili:    ",
        "stat_owned": " * Sahibi:    ",
        "stat_admin": " ! Yönetici:  ",
        "stat_staff": " + Yetkili:   ",
        "stat_locked": " (kilitli)",
        "stat_will_leave": " » Ayrılınacak:",
        "stat_more": "  … ve {n} tane daha",
        "stat_nothing": " Henüz bir şey seçilmedi.",
        "key_space": "Boşluk",
        "key_toggle": "seç/kaldır",
        "key_select_all": "hepsini seç",
        "key_select_regular": "yetkisizler",
        "key_deselect_all": "temizle",
        "key_search": "ara",
        "key_move": "gezin",
        "key_confirm": "onayla",
        "key_back": "geri",
        "key_quit": "çık",
        "frame_servers": " Sunucular (A-Z) ",
        "frame_search": " Ara  ( / ) ",
        "frame_selection": " Seçim ",
        "sel_warning": "! Hiç sunucu seçmedin — en az bir tane seç!",
        "confirm_panel_title": "! ONAY GEREKLİ",
        "confirm_title": "» Şu sunuculardan AYRILMAK üzeresin:",
        "confirm_count": "• Sunucu sayısı:  [bold bright_red]{n}[/bold bright_red] {noun}",
        "confirm_client": "• Uygulama:       [bold cyan]{clients}[/bold cyan]",
        "confirm_eta": "• Tahmini süre:   [bold yellow]{eta}[/bold yellow]",
        "confirm_servers": "» Seçilen sunucular:",
        "confirm_prompt": (
            "[bold]» Devam etmek için [bold bright_red]CONFIRM[/bold bright_red] yaz, "
            "geri dönmek için [dim]Enter[/dim]'a bas[/bold]"
        ),
        "est_seconds": "~{n} saniye",
        "cancelled": "× İptal edildi. Hiçbir sunucudan ayrılınmadı.",
        "going_back": "« Geri dönülüyor...",
        "exec_title": "Sunuculardan Ayrılıyor",
        "status_left": "+ Ayrıldı",
        "status_skipped": "! Atlandı",
        "status_error": "× Hata",
        "status_leaving": "» Ayrılıyor...",
        "status_waiting": "… Güvenli bekleme {s}sn",
        "eta": "Kalan",
        "col_server": "Sunucu",
        "col_status": "Durum",
        "col_detail": "Detay",
        "hidden_rows": "… önceki {n} sonuç gizlendi",
        "detail_left": "Ayrıldı",
        "detail_owner": "Sahibi",
        "detail_forbidden": "{name} sunucusundan ayrılınamıyor (yasak)",
        "detail_404": "Bilinmeyen sunucu (404)",
        "detail_unexpected": "Beklenmeyen durum kodu {status}",
        "err_network": "Ağ hatası: {name}",
        "err_429": "Çok fazla hız sınırına takıldı (429).",
        "err_5xx": "Discord sunucu hatası ({status}).",
        "err_account": "Hesap bilgisi alınamadı ({status}).",
        "err_bot": "Bot hesapları desteklenmiyor — kullanıcı hesabı token'ı kullan.",
        "err_guilds": "Sunucular alınamadı ({status}).",
        "err_401": "Token geçersiz veya iptal edilmiş (HTTP 401). İşlem durduruldu.",
        "err_unexpected": "Beklenmeyen hata: {name}: {msg}",
        "sum_title": "Özet",
        "sum_left": "+ Ayrılınan:",
        "sum_skipped_owner": "* Atlanan (sahibi):",
        "sum_skipped_forbidden": "! Atlanan (yasak):",
        "sum_errors": "× Hatalar:",
        "sum_time": "• Toplam süre:",
        "sum_owned_note": "* {s} sahibisin, atlandı.",
        "interrupted": "! İşlem durduruldu. Temizleniyor...",
        "token_wiped": "+ Token bellekten güvenle silindi.",
        "clipboard_prompt": "Token hâlâ panonda kopyalı — temizlensin mi?",
        "clipboard_yes": "Evet — panoyu temizle",
        "clipboard_no": "Hayır — kalsın",
        "clipboard_cleared": "+ Pano temizlendi.",
    },
}


def set_language(code: str) -> None:
    """Set the active UI language (``"tr"`` or ``"en"``)."""
    global _current
    _current = code if code in SUPPORTED else "en"


def get_language() -> str:
    """Return the active UI language code."""
    return _current


def detect_default_language() -> str:
    """Guess the preferred language from ``DSL_LANG`` or the OS locale (``tr`` or ``en``)."""
    env = os.environ.get("DSL_LANG", "").strip().lower()
    if env in SUPPORTED:
        return env
    try:
        name = (locale.getlocale()[0] or "").lower()
    except ValueError:
        name = ""
    return "tr" if name.startswith(("tr", "turkish")) else "en"


def t(key: str, **kwargs: Any) -> str:
    """Return the translated string for ``key`` formatted with ``kwargs``."""
    table = STRINGS.get(_current, STRINGS["en"])
    template = table.get(key) or STRINGS["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def servers(n: int) -> str:
    """Return the localized noun for ``n`` servers (``server``/``servers`` or ``sunucu``)."""
    if _current == "tr":
        return "sunucu"
    return "server" if n == 1 else "servers"


def count_servers(n: int) -> str:
    """Return e.g. ``"3 servers"`` / ``"3 sunucu"``."""
    return f"{n} {servers(n)}"
