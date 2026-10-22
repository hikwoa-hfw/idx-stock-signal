"""Telegram Bot Commands definition and helper utilities.

Registers command list with Telegram Bot API so when users type `/`
in Telegram, the UI displays the interactive command menu.
"""

from __future__ import annotations

import re
from typing import Any

# Canonical bot commands list adhering to Telegram Bot API specifications:
# - command: 1-32 lowercase characters (a-z, 0-9, _)
# - description: 1-256 characters
DEFAULT_BOT_COMMANDS: list[dict[str, str]] = [
    {
        "command": "start",
        "description": "Start the bot & display welcome instructions",
    },
    {
        "command": "help",
        "description": "Display command list and usage guide",
    },
    {
        "command": "daily",
        "description": "Latest ranked daily BUY signals",
    },
    {
        "command": "signals",
        "description": "Recent trading signal IDs and summary",
    },
    {
        "command": "status",
        "description": "Daily pipeline & prospective observation status",
    },
    {
        "command": "pipeline",
        "description": "Latest daily pipeline execution run summary",
    },
    {
        "command": "portfolio",
        "description": "Active open positions and unrealized PnL",
    },
    {
        "command": "positions",
        "description": "Active open positions and unrealized PnL",
    },
    {
        "command": "enter",
        "description": "Open manual position: <TICKER> <PRICE> <QTY>",
    },
    {
        "command": "exit",
        "description": "Close position: <TICKER_OR_ID> <PRICE> [REASON]",
    },
    {
        "command": "cancel",
        "description": "Cancel open position: <TICKER_OR_ID> [REASON]",
    },
    {
        "command": "model",
        "description": "Champion model version and evaluation metrics",
    },
    {
        "command": "compare",
        "description": "Compare champion vs challenger models",
    },
    {
        "command": "performance",
        "description": "Out-of-sample performance evaluation",
    },
]


def validate_bot_commands(commands: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validate and sanitize a list of bot commands per Telegram API rules."""
    sanitized: list[dict[str, str]] = []
    seen: set[str] = set()

    for cmd_dict in commands:
        raw_cmd = str(cmd_dict.get("command", "")).strip().lstrip("/").lower()
        desc = str(cmd_dict.get("description", "")).strip()

        if not raw_cmd or not desc:
            continue

        if not re.match(r"^[a-z0-9_]{1,32}$", raw_cmd):
            raise ValueError(
                f"Invalid command name '{raw_cmd}'. Telegram commands must be 1-32 "
                "characters of lowercase latin letters, digits, and underscores."
            )

        if len(desc) > 256:
            desc = desc[:256]

        if raw_cmd not in seen:
            seen.add(raw_cmd)
            sanitized.append({"command": raw_cmd, "description": desc})

    return sanitized


def get_bot_commands() -> list[dict[str, str]]:
    """Return validated default bot commands."""
    return validate_bot_commands(DEFAULT_BOT_COMMANDS)


def format_commands_for_botfather(commands: list[dict[str, str]] | None = None) -> str:
    """Format commands for copy-pasting into Telegram @BotFather /setcommands."""
    cmds = commands or get_bot_commands()
    return "\n".join(f"{c['command']} - {c['description']}" for c in cmds)
