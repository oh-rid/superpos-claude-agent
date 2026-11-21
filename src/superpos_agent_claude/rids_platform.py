"""Bot platform (rids): the agent tells the platform who its Telegram bot is.

The platform shows the agent under its bot's own name and @username (owner,
2026-11-21: "it comes from the bot's own settings"). The platform never holds
the bot token, so the agent asks Telegram itself (getMe, cached for
REFRESH_SECONDS) and adds ``telegram_bot: {username, first_name}`` to every
heartbeat. Renaming the bot in @BotFather reaches the admin card within
REFRESH_SECONDS. Superpos ignored unknown heartbeat keys, so the extra field is
protocol-safe.
"""
from __future__ import annotations

import logging
import os
import time

import httpx
import superpos_agent_core.superpos_client as _core_client

log = logging.getLogger(__name__)

REFRESH_SECONDS = 600
HEARTBEAT_PATH = "/agents/heartbeat"

_identity: dict = {}
_checked_at: float | None = None
_transport: httpx.AsyncBaseTransport | None = None   # tests inject a MockTransport


async def telegram_bot_identity() -> dict:
    """{username, first_name} of this agent's bot, or {} when unknown.

    Never raises and never logs the token (httpx errors embed the URL, which
    carries it — only the exception type is logged)."""
    global _checked_at
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {}
    now = time.monotonic()
    if _checked_at is not None and now - _checked_at < REFRESH_SECONDS:
        return dict(_identity)
    _checked_at = now
    try:
        async with httpx.AsyncClient(timeout=5, transport=_transport) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            me = (resp.json() or {}).get("result") or {}
        if me.get("username"):
            _identity.clear()
            _identity.update({"username": str(me["username"]),
                              "first_name": str(me.get("first_name") or "")})
    except Exception as exc:          # noqa: BLE001 — a heartbeat must never fail on this
        log.warning("Telegram getMe failed (%s); keeping last known bot identity",
                    type(exc).__name__)
    return dict(_identity)


_original_request = _core_client.SuperposClient._request


async def _request_with_bot(self, method: str, path: str, **kwargs):
    if method == "POST" and path.endswith(HEARTBEAT_PATH):
        bot = await telegram_bot_identity()
        if bot:
            kwargs["json"] = {**(kwargs.get("json") or {}), "telegram_bot": bot}
    return await _original_request(self, method, path, **kwargs)


def install() -> None:
    _core_client.SuperposClient._request = _request_with_bot
