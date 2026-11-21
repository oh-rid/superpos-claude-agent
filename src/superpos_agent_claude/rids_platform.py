"""Bot platform (rids): the agent tells the platform who its Telegram bot is —
only when the platform asks.

The platform shows the agent under its bot's own name and @username (owner,
2026-11-21: "it comes from the bot's own settings"), but never holds the bot
token. So the agent asks Telegram (getMe) — and ONLY when the platform's
heartbeat answer says ``want_telegram_bot`` (it has no name yet, i.e. first
connection, or the owner pressed "Обновить из Telegram"). Owner: "once when the
agent is created, then by the button — not every 10 minutes". The identity
rides on the next heartbeat; the platform then stops asking.

Superpos ignored unknown heartbeat keys and never sent ``want_telegram_bot``,
so this is protocol-safe in both directions.
"""
from __future__ import annotations

import logging
import os
import time

import httpx
import superpos_agent_core.superpos_client as _core_client

log = logging.getLogger(__name__)

HEARTBEAT_PATH = "/agents/heartbeat"
RETRY_SECONDS = 60     # a failing getMe is retried at most once a minute, not every heartbeat

_asked = False                     # the platform's last heartbeat answer asked for the bot
_last_try: float | None = None
_transport: httpx.AsyncBaseTransport | None = None   # tests inject a MockTransport


async def fetch_bot_identity() -> dict:
    """One getMe: {username, first_name}, or {} on any failure.

    Never raises and never logs the token (httpx errors embed the URL, which
    carries it — only the exception type is logged)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {}
    try:
        async with httpx.AsyncClient(timeout=5, transport=_transport) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            me = (resp.json() or {}).get("result") or {}
        if me.get("username"):
            return {"username": str(me["username"]),
                    "first_name": str(me.get("first_name") or "")}
    except Exception as exc:          # noqa: BLE001 — a heartbeat must never fail on this
        log.warning("Telegram getMe failed (%s)", type(exc).__name__)
    return {}


_original_request = _core_client.SuperposClient._request


async def _request_with_bot(self, method: str, path: str, **kwargs):
    global _asked, _last_try
    is_heartbeat = method == "POST" and path.endswith(HEARTBEAT_PATH)
    if is_heartbeat and _asked:
        now = time.monotonic()
        if _last_try is None or now - _last_try >= RETRY_SECONDS:
            _last_try = now
            bot = await fetch_bot_identity()
            if bot:
                kwargs["json"] = {**(kwargs.get("json") or {}), "telegram_bot": bot}
    resp = await _original_request(self, method, path, **kwargs)
    if is_heartbeat:
        try:
            data = (resp.json() or {}).get("data") or {}
            asked_now = bool(data.get("want_telegram_bot"))
        except Exception:             # noqa: BLE001 — empty/odd body: nothing asked
            asked_now = False
        if asked_now and not _asked:
            _last_try = None          # a fresh request (button) is served at once
        _asked = asked_now
    return resp


def install() -> None:
    _core_client.SuperposClient._request = _request_with_bot
