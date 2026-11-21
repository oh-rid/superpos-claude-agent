"""Bot platform (rids): heartbeat carries the agent's own Telegram bot identity."""
import logging

import httpx
import pytest

import superpos_agent_claude.rids_platform as rp


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(rp, "_identity", {})
    monkeypatch.setattr(rp, "_checked_at", None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRET-token-value")
    yield


def _telegram(payload_or_exc, calls):
    def handler(request):
        calls.append(str(request.url))
        if isinstance(payload_or_exc, Exception):
            raise payload_or_exc
        return httpx.Response(200, json=payload_or_exc)
    return httpx.MockTransport(handler)


async def test_identity_from_getme_and_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(rp, "_transport", _telegram(
        {"ok": True, "result": {"username": "mwagner_bot", "first_name": "Wags"}}, calls))
    assert await rp.telegram_bot_identity() == {"username": "mwagner_bot", "first_name": "Wags"}
    assert await rp.telegram_bot_identity() == {"username": "mwagner_bot", "first_name": "Wags"}
    assert len(calls) == 1 and calls[0].endswith("/getMe")


async def test_getme_failure_keeps_heartbeat_alive_and_hides_token(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(rp, "_transport", _telegram(httpx.ConnectError("boom"), calls))
    with caplog.at_level(logging.DEBUG):
        assert await rp.telegram_bot_identity() == {}
    assert "SECRET" not in caplog.text


async def test_only_heartbeat_gets_the_bot_field(monkeypatch):
    sent = []

    async def fake_original(self, method, path, **kwargs):
        sent.append((method, path, kwargs.get("json")))

    async def fake_identity():
        return {"username": "mwagner_bot", "first_name": "Wags"}

    monkeypatch.setattr(rp, "_original_request", fake_original)
    monkeypatch.setattr(rp, "telegram_bot_identity", fake_identity)
    await rp._request_with_bot(None, "POST", "/api/v1/agents/heartbeat", json={"model": "opus"})
    await rp._request_with_bot(None, "POST", "/api/v1/agents/heartbeat", json=None)
    await rp._request_with_bot(None, "PATCH", "/api/v1/agents/status", json={"status": "online"})
    assert sent[0][2] == {"model": "opus", "telegram_bot": {"username": "mwagner_bot", "first_name": "Wags"}}
    assert sent[1][2] == {"telegram_bot": {"username": "mwagner_bot", "first_name": "Wags"}}
    assert sent[2][2] == {"status": "online"}


def test_entry_point_installs_the_patch():
    import importlib

    import superpos_agent_core.superpos_client as core_client
    importlib.import_module("superpos_agent_claude.__main__")
    assert core_client.SuperposClient._request is rp._request_with_bot
