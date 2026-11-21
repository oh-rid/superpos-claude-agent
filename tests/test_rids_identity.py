"""Bot platform (rids): the agent asks Telegram for its bot identity only when
the platform's heartbeat answer asks for it — never on a timer."""
import logging

import httpx
import pytest

import superpos_agent_claude.rids_platform as rp

BOT = {"username": "mwagner_bot", "first_name": "Wags"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(rp, "_asked", False)
    monkeypatch.setattr(rp, "_last_try", None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRET-token-value")
    yield


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return {"data": self._data, "meta": {}, "errors": None}


def _platform(answers, sent):
    """Fake core _request: records bodies, answers heartbeats from a script."""
    async def fake(self, method, path, **kwargs):
        sent.append((method, path, kwargs.get("json")))
        return _Resp(answers.pop(0) if path.endswith("/heartbeat") else {})
    return fake


def _telegram(monkeypatch, result=None, exc=None):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if exc:
            raise exc
        return httpx.Response(200, json={"ok": True, "result": result})
    monkeypatch.setattr(rp, "_transport", httpx.MockTransport(handler))
    return calls


async def _hb(n=1):
    for _ in range(n):
        await rp._request_with_bot(None, "POST", "/api/v1/agents/heartbeat", json={"model": "opus"})


async def test_no_telegram_calls_unless_platform_asks(monkeypatch):
    sent, calls = [], _telegram(monkeypatch, BOT)
    monkeypatch.setattr(rp, "_original_request", _platform([{"want_telegram_bot": False}] * 5, sent))
    await _hb(5)
    assert calls == [] and all("telegram_bot" not in (b or {}) for _, _, b in sent)


async def test_asked_once_sends_identity_once_then_stops(monkeypatch):
    sent, calls = [], _telegram(monkeypatch, BOT)
    answers = [{"want_telegram_bot": True}, {"want_telegram_bot": False},
               {"want_telegram_bot": False}, {"want_telegram_bot": False}]
    monkeypatch.setattr(rp, "_original_request", _platform(answers, sent))
    await _hb(4)
    assert len(calls) == 1 and calls[0].endswith("/getMe")
    assert "telegram_bot" not in sent[0][2]                     # first heartbeat: not asked yet
    assert sent[1][2] == {"model": "opus", "telegram_bot": BOT}  # answered the ask
    assert all("telegram_bot" not in b for _, _, b in sent[2:])


async def test_button_press_later_triggers_one_fresh_call(monkeypatch):
    sent, calls = [], _telegram(monkeypatch, BOT)
    answers = [{"want_telegram_bot": True}, {"want_telegram_bot": False},
               {"want_telegram_bot": True}, {"want_telegram_bot": False}]
    monkeypatch.setattr(rp, "_original_request", _platform(answers, sent))
    await _hb(4)
    assert len(calls) == 2 and "telegram_bot" in sent[3][2]


async def test_failing_getme_is_not_hammered_and_hides_token(monkeypatch, caplog):
    sent = []
    calls = _telegram(monkeypatch, exc=httpx.ConnectError("boom"))
    monkeypatch.setattr(rp, "_original_request", _platform([{"want_telegram_bot": True}] * 6, sent))
    with caplog.at_level(logging.DEBUG):
        await _hb(6)
    assert len(calls) == 1                     # retried at most once a minute, not per heartbeat
    assert "SECRET" not in caplog.text


async def test_other_requests_untouched(monkeypatch):
    sent, calls = [], _telegram(monkeypatch, BOT)
    monkeypatch.setattr(rp, "_asked", True)
    monkeypatch.setattr(rp, "_original_request", _platform([], sent))
    await rp._request_with_bot(None, "PATCH", "/api/v1/agents/status", json={"status": "online"})
    assert calls == [] and sent == [("PATCH", "/api/v1/agents/status", {"status": "online"})]


def test_entry_point_installs_the_patch():
    import importlib

    import superpos_agent_core.superpos_client as core_client
    importlib.import_module("superpos_agent_claude.__main__")
    assert core_client.SuperposClient._request is rp._request_with_bot
