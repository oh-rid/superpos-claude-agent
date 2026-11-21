"""Superpos-Agent-Claude entry point — wires ClaudeExecutor into the core orchestrator."""

from __future__ import annotations

import asyncio
import logging

import superpos_agent_core.main as _core_main
from superpos_agent_core import run_agent

from . import rids_platform
from .claude_executor import ClaudeExecutor
from .config import ClaudeConfig
from .runtime_config import ClaudeRuntimeConfig

log = logging.getLogger(__name__)

# Bot platform (rids): the task server deliberately grants only the task
# lifecycle (tasks:read/claim/update) — no sub-task creation, no knowledge
# writes. Core would otherwise post "grant them in the Superpos dashboard" to
# Telegram on every start; that dashboard no longer exists for this agent.
# Required permissions are still checked and reported.
_core_main._OPTIONAL_PERMISSIONS = ()

# Heartbeat carries the agent's own Telegram bot name/@username (rids_platform).
rids_platform.install()


async def main() -> None:
    config = ClaudeConfig.from_env()
    runtime = ClaudeRuntimeConfig.load(
        default_model=config.claude_model,
        default_effort=config.claude_effort,
        home_dir=config.home_dir,
    )

    def _factory(cfg, rt, superpos, gateway, persona):
        return ClaudeExecutor(cfg, rt, superpos, gateway, persona=persona)

    await run_agent(config, runtime, executor_factory=_factory)


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
