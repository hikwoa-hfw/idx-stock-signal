"""CLI script to register Bot Commands with Telegram API (setMyCommands).

When registered, Telegram clients display an interactive menu when the user types '/'.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from python.config.settings import settings
from services.telegram.client import TelegramClient
from services.telegram.commands import format_commands_for_botfather, get_bot_commands


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register Telegram Bot Commands for the interactive '/' popup menu."
    )
    parser.add_argument(
        "--bot-token",
        type=str,
        default=None,
        help="Telegram Bot Token (default: env TELEGRAM_BOT_TOKEN).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Display commands without sending API request.",
    )
    parser.add_argument(
        "--botfather",
        action="store_true",
        help="Print command list formatted for @BotFather /setcommands.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete all registered bot commands.",
    )
    args = parser.parse_args(argv)

    commands = get_bot_commands()

    if args.botfather:
        sys.stdout.write("--- Copy and paste the following to @BotFather /setcommands ---\n")
        sys.stdout.write(format_commands_for_botfather(commands) + "\n")
        return 0

    if args.dry_run:
        sys.stdout.write(f"[DRY-RUN] Would register {len(commands)} commands with Telegram API:\n")
        sys.stdout.write(json.dumps(commands, indent=2) + "\n")
        return 0

    token = args.bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or settings.telegram_bot_token
    if not token:
        sys.stderr.write("ERROR: TELEGRAM_BOT_TOKEN is not set.\n")
        return 1

    client = TelegramClient(bot_token=token)

    if args.delete:
        sys.stdout.write("Deleting Telegram bot commands...\n")
        res = client.delete_my_commands()
        sys.stdout.write(f"Result: {json.dumps(res)}\n")
        return 0

    sys.stdout.write(f"Registering {len(commands)} bot commands with Telegram (setMyCommands)...\n")
    res = client.set_my_commands(commands)
    sys.stdout.write(f"SUCCESS: {json.dumps(res)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
