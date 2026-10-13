import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Optional, Sequence

from python.common.types import SignalRecord
from python.config.settings import settings
from services.telegram.formatter import format_daily_signals

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def mask_token(token: Optional[str]) -> str:
    """Mask Telegram bot token to prevent plaintext leakage in logs or repr."""
    if not token:
        return "[NOT_SET]"
    clean = token.strip()
    if len(clean) <= 8:
        return "***"
    return f"{clean[:4]}...{clean[-4:]}"


def split_message(text: str, max_chars: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Splits message text into chunks <= max_chars along logical boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    # Prefer splitting along candidate block dividers
    divider = "━━━━━━━━━━━━━━━━\n\n"
    if divider in text:
        blocks = text.split(f"\n\n{divider}")
    else:
        blocks = text.split("\n\n")

    current = ""
    for idx, blk in enumerate(blocks):
        candidate_text = blk if idx == 0 else f"{divider}{blk}"
        candidate_to_add = candidate_text if not current else f"{current}\n\n{candidate_text}"

        if len(candidate_to_add) <= max_chars:
            current = candidate_to_add
        else:
            if current:
                chunks.append(current)
            if len(candidate_text) <= max_chars:
                current = candidate_text
            else:
                # Oversized block: split line by line
                lines = candidate_text.split("\n")
                line_accum = ""
                for line in lines:
                    to_add = line if not line_accum else f"{line_accum}\n{line}"
                    if len(to_add) <= max_chars:
                        line_accum = to_add
                    else:
                        if line_accum:
                            chunks.append(line_accum)
                        line_accum = line[:max_chars]
                current = line_accum

    if current:
        chunks.append(current)

    return chunks if chunks else [text[:max_chars]]


class TelegramError(Exception):
    """Exception raised for Telegram API and network errors with token masked."""

    pass


class TelegramClient:
    """Lightweight Telegram Bot API client using standard library urllib."""

    # ponytail: urllib.request stdlib client used; add httpx/aiohttp if async webhook daemon needed.
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        base_url: str = "https://api.telegram.org",
        token: Optional[str] = None,
    ) -> None:
        effective_token = bot_token if bot_token is not None else token
        self.bot_token = (
            effective_token if effective_token is not None else settings.telegram_bot_token
        )
        self.chat_id = chat_id if chat_id is not None else settings.telegram_chat_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = base_url.rstrip("/")

    def __repr__(self) -> str:
        return (
            f"TelegramClient(bot_token='{mask_token(self.bot_token)}', "
            f"chat_id='{self.chat_id}', max_retries={self.max_retries})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def _sanitize(self, message: str) -> str:
        sanitized = message
        if self.bot_token and self.bot_token in sanitized:
            sanitized = sanitized.replace(self.bot_token, mask_token(self.bot_token))
        # Mask any Telegram bot token pattern (e.g. bot123456789:ABCdef...)
        sanitized = re.sub(r"bot(\d{5,}:[A-Za-z0-9_-]{10,})", r"bot***:***", sanitized)
        return sanitized

    def _parse_retry_after(self, e: urllib.error.HTTPError, raw_err: str) -> float:
        """Extract retry delay from Retry-After header or Telegram error parameters."""
        if hasattr(e, "headers") and e.headers:
            header_val = e.headers.get("Retry-After")
            if header_val:
                try:
                    return min(max(float(header_val), 0.5), 60.0)
                except (ValueError, TypeError):
                    pass
        if raw_err:
            try:
                data = json.loads(raw_err)
                if isinstance(data, dict):
                    params = data.get("parameters", {})
                    sec = params.get("retry_after")
                    if sec is not None:
                        return min(max(float(sec), 0.5), 60.0)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        return 1.0

    def _urlopen(self, req: Any) -> Any:
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                import ssl

                ctx = ssl._create_unverified_context()
                return urllib.request.urlopen(req, timeout=self.timeout, context=ctx)
            raise

    def _send_payload(
        self,
        text: str,
        target_chat: str,
        parse_mode: Optional[str] = "Markdown",
    ) -> dict[str, Any]:
        """Send a single chunk with bounded retries and error handling."""
        endpoint = f"{self.base_url}/bot{self.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": target_chat,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "IndonesianStockAI/1.0",
            },
            method="POST",
        )

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                with self._urlopen(req) as resp:
                    resp_bytes = resp.read()
                    data_dict: dict[str, Any] = json.loads(resp_bytes.decode("utf-8"))
                    if not data_dict.get("ok", False):
                        err_desc = self._sanitize(data_dict.get("description", "Unknown error"))
                        raise TelegramError(f"Telegram API returned error: {err_desc}")
                    return data_dict

            except urllib.error.HTTPError as e:
                raw_err = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
                sanitized_msg = self._sanitize(f"HTTP {e.code} ({e.reason}): {raw_err}")
                logger.error(
                    "Telegram API HTTP error (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    sanitized_msg,
                )
                last_error = TelegramError(sanitized_msg)

                # Graceful fallback on markdown parse error: retry once without parse_mode
                if e.code == 400 and parse_mode and "can't parse entities" in raw_err.lower():
                    logger.warning("Markdown parse failed; falling back to plaintext delivery.")
                    return self._send_payload(text=text, target_chat=target_chat, parse_mode=None)

                # HTTP 429 Rate Limit: adaptive backoff
                if e.code == 429:
                    sleep_sec = self._parse_retry_after(e, raw_err)
                    if attempt < self.max_retries - 1:
                        time.sleep(sleep_sec)
                        continue

                # HTTP 4xx fail-fast for unrecoverable errors (except 429 handled above)
                if 400 <= e.code < 500:
                    break

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                sanitized_msg = self._sanitize(str(e))
                logger.warning(
                    "Telegram network error (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    sanitized_msg,
                )
                last_error = TelegramError(sanitized_msg)

            if attempt < self.max_retries - 1:
                sleep_sec = 0.5 * (2**attempt)
                time.sleep(sleep_sec)

        raise TelegramError(
            f"Failed to send Telegram message after {self.max_retries} attempts: {last_error}"
        )

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: Optional[str] = "Markdown",
    ) -> dict[str, Any]:
        """Send message text to specified chat_id via Telegram Bot API with chunking support."""
        target_chat = chat_id or self.chat_id
        if not self.bot_token:
            raise TelegramError("Cannot send message: TELEGRAM_BOT_TOKEN is not configured.")
        if not target_chat:
            raise TelegramError("Cannot send message: TELEGRAM_CHAT_ID is not configured.")

        chunks = split_message(text, max_chars=TELEGRAM_MAX_MESSAGE_LENGTH)
        last_resp: dict[str, Any] = {}

        for chunk in chunks:
            last_resp = self._send_payload(
                text=chunk, target_chat=target_chat, parse_mode=parse_mode
            )

        if len(chunks) > 1:
            last_resp["chunks_sent"] = len(chunks)

        return last_resp

    def broadcast_daily_signals(
        self,
        signals: Sequence[SignalRecord],
        market_summary: Optional[dict[str, str]] = None,
        chat_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Format and broadcast daily signals to Telegram channel or chat."""
        formatted_text = format_daily_signals(signals=signals, market_summary=market_summary)
        return self.send_message(text=formatted_text, chat_id=chat_id)

    def set_webhook(
        self,
        url: str,
        secret_token: Optional[str] = None,
        drop_pending_updates: bool = False,
    ) -> dict[str, Any]:
        """Configure Telegram webhook endpoint."""
        if not self.bot_token:
            raise TelegramError("Cannot set webhook: TELEGRAM_BOT_TOKEN is not configured.")
        endpoint = f"{self.base_url}/bot{self.bot_token}/setWebhook"
        payload: dict[str, Any] = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        if drop_pending_updates:
            payload["drop_pending_updates"] = True

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._urlopen(req) as resp:
                data_dict: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                if not data_dict.get("ok", False):
                    err_desc = self._sanitize(data_dict.get("description", "Unknown error"))
                    raise TelegramError(f"Telegram API setWebhook error: {err_desc}")
                return data_dict
        except Exception as e:
            raise TelegramError(f"Failed to set webhook: {self._sanitize(str(e))}") from e

    def get_webhook_info(self) -> dict[str, Any]:
        """Fetch current Telegram webhook configuration and status."""
        if not self.bot_token:
            raise TelegramError("Cannot get webhook info: TELEGRAM_BOT_TOKEN is not configured.")
        endpoint = f"{self.base_url}/bot{self.bot_token}/getWebhookInfo"
        try:
            with self._urlopen(endpoint) as resp:
                data_dict: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                if not data_dict.get("ok", False):
                    err_desc = self._sanitize(data_dict.get("description", "Unknown error"))
                    raise TelegramError(f"Telegram API getWebhookInfo error: {err_desc}")
                return data_dict
        except Exception as e:
            raise TelegramError(f"Failed to get webhook info: {self._sanitize(str(e))}") from e

    def delete_webhook(self, drop_pending_updates: bool = False) -> dict[str, Any]:
        """Remove Telegram webhook and revert to getUpdates mode."""
        if not self.bot_token:
            raise TelegramError("Cannot delete webhook: TELEGRAM_BOT_TOKEN is not configured.")
        endpoint = f"{self.base_url}/bot{self.bot_token}/deleteWebhook"
        payload = {"drop_pending_updates": drop_pending_updates}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._urlopen(req) as resp:
                data_dict: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                if not data_dict.get("ok", False):
                    err_desc = self._sanitize(data_dict.get("description", "Unknown error"))
                    raise TelegramError(f"Telegram API deleteWebhook error: {err_desc}")
                return data_dict
        except Exception as e:
            raise TelegramError(f"Failed to delete webhook: {self._sanitize(str(e))}") from e

