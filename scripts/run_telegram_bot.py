"""Interactive Telegram Bot Polling Daemon.

Listens for incoming Telegram commands (/start, /daily, /positions, /model, /enter, /exit)
and replies using TelegramBotDispatcher.
"""

import json
import logging
import signal
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

from python.config.settings import settings
from services.telegram.bot import TelegramBotDispatcher
from services.telegram.client import TelegramClient, mask_token

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("telegram_bot_daemon")


def run_poller(poll_timeout: int = 30) -> None:
    token = settings.telegram_bot_token
    if not token:
        sys.stderr.write("[ERROR] TELEGRAM_BOT_TOKEN is not configured in .env\n")
        sys.exit(1)

    logger.info("Starting Telegram Bot poller for token: %s", mask_token(token))
    dispatcher = TelegramBotDispatcher()
    client = TelegramClient(bot_token=token)

    running = True

    def _handle_exit(sig, frame):  # noqa: ANN001, ARG001
        nonlocal running
        logger.info("Stopping Telegram Bot poller gracefully...")
        running = False

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    offset: Optional[int] = None
    logger.info("Bot is ONLINE and listening for commands. Send /start or /help in Telegram!")

    while running:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?timeout={poll_timeout}"
            if offset is not None:
                url += f"&offset={offset}"

            req = urllib.request.Request(url, headers={"User-Agent": "IDXStockBot/1.0"})
            with urllib.request.urlopen(req, timeout=poll_timeout + 5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not data.get("ok"):
                logger.warning("getUpdates response not ok: %s", data)
                time.sleep(2)
                continue

            updates = data.get("result", [])
            for u in updates:
                update_id = u["update_id"]
                offset = update_id + 1

                msg = u.get("message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                text = msg.get("text", "")
                user_info = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name", "user")

                if not text or not chat_id:
                    continue

                logger.info("Received from %s (%s): %s", user_info, chat_id, text)

                # Process command via decoupled dispatcher
                reply_text = dispatcher.dispatch(text)

                # Send response back to user
                client.send_message(text=reply_text, chat_id=str(chat_id))
                logger.info("Replied to %s (%s) [%d chars]", user_info, chat_id, len(reply_text))

        except urllib.error.URLError as url_err:
            logger.warning("Network error in poller: %s. Retrying in 3s...", url_err)
            time.sleep(3)
        except Exception as exc:
            logger.error("Error in bot poller: %s", exc)
            time.sleep(2)


if __name__ == "__main__":
    run_poller()
