"""Telegram delivery for daily digests (best-effort, never raises).

Sends through the keyless Bot API ``sendMessage`` endpoint. A no-op unless both
``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` are configured (secrets stay
server-side, never logged). Long messages are split on line boundaries to stay
under Telegram's 4096-character hard limit.
"""

from __future__ import annotations

import html

import httpx

from us_watcher.config import get_settings
from us_watcher.infrastructure.http import new_async_client
from us_watcher.logging_config import get_logger

log = get_logger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"
_LIMIT = 3800  # under Telegram's 4096 cap, leaving headroom for HTML entities


def esc(text: str) -> str:
    """Escape a dynamic string for Telegram HTML parse mode."""
    return html.escape(str(text), quote=False)


def _chunks(text: str, size: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > size:
            if buf:
                out.append(buf)
            buf = line
            while len(buf) > size:  # a single over-long line
                out.append(buf[:size])
                buf = buf[size:]
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        out.append(buf)
    return out


async def send_telegram(text: str, *, parse_mode: str = "HTML") -> bool:
    """Send ``text`` to the configured chat. Returns True on full success."""
    settings = get_settings()
    if not settings.telegram_enabled:
        log.info("telegram.disabled")
        return False
    url = _API.format(token=settings.telegram_bot_token.get_secret_value())
    chat_id = settings.telegram_chat_id
    try:
        async with new_async_client(timeout=15.0) as client:
            for chunk in _chunks(text, _LIMIT):
                resp = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code != 200:
                    log.warning("telegram.send_failed", status=resp.status_code, body=resp.text[:200])
                    return False
    except httpx.HTTPError as exc:
        log.warning("telegram.send_error", error=str(exc))
        return False
    log.info("telegram.sent", chars=len(text))
    return True
