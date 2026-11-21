"""Bot platform (rids) patches: turn separator and optional-permission nag."""
import importlib
from unittest.mock import AsyncMock, patch

import superpos_agent_core.main as core_main
from superpos_agent_core import ExecutionRequest


def test_optional_permission_nag_is_off_but_required_check_stays():
    assert hasattr(core_main, "_OPTIONAL_PERMISSIONS"), "core renamed the constant"
    importlib.import_module("superpos_agent_claude.__main__")
    assert core_main._OPTIONAL_PERMISSIONS == ()
    assert "tasks:claim" in core_main._REQUIRED_PERMISSIONS


async def test_model_turns_are_separated_in_telegram_and_in_task_result(executor, mock_config):
    """Two model turns with a tool call between them used to arrive glued:
    "Running it now.готово" — in Telegram and in the stored task result."""
    from claude_agent_sdk.types import (
        AssistantMessage, ResultMessage, SystemMessage, TextBlock,
    )

    mock_config.executor_worktree_isolation = False
    req = ExecutionRequest(prompt="x", chat_id="123", source="superpos",
                           superpos_task_id="t-sep")

    async def _stream():
        yield SystemMessage(subtype="init", data={"session_id": "s"})
        yield AssistantMessage(content=[TextBlock(text="Running it now.")], model="m")
        yield AssistantMessage(content=[TextBlock(text="готово")], model="m")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                            is_error=False, num_turns=2, session_id="s", result="готово")

    with patch("superpos_agent_claude.claude_executor.query", side_effect=lambda **kw: _stream()), \
         patch("superpos_agent_claude.claude_executor.TelegramStreamer") as MockStreamer:
        streamer = MockStreamer.return_value
        streamer.append = AsyncMock()
        streamer.finish = AsyncMock()
        streamer.send_tool_notification = AsyncMock()
        await executor._execute_inner(req, streamer, retries=1)

    sent = "".join(c.args[0] for c in streamer.append.await_args_list)
    assert sent == "Running it now.\n\nготово"
    result = executor._superpos.complete_task.await_args.args[1]
    assert result == "Running it now.\n\nготово"
