import io
import json
import urllib.error
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from python.common.types import SignalRecord
from python.models.registry import ModelMetadata, ModelRegistry
from python.signals.repository import SignalRepository
from services.telegram.bot import TelegramBotDispatcher
from services.telegram.client import TelegramClient, TelegramError, mask_token, split_message
from services.telegram.commands import (
    format_commands_for_botfather,
    get_bot_commands,
    validate_bot_commands,
)
from services.telegram.formatter import (
    _derive_market_summary,
    _format_pct,
    derive_rationale,
    format_daily_signals,
)


def _sample_signal(
    ticker: str = "ANTM",
    score: float = 91.0,
    prob: float = 0.74,
    exp_ret: float = 0.038,
    entry_low: float = 3950.0,
    entry_high: float = 4000.0,
    tp_price: float = 4200.0,
    sl_price: float = 3871.0,
    max_holding_days: int = 10,
    s_date: date = date(2026, 10, 6),
    snapshot: dict | None = None,
) -> SignalRecord:
    snap = snapshot or {
        "return_5d": 0.03,
        "volume_ratio_20d": 1.5,
        "rel_strength_sector_20d": 0.02,
        "market_breadth": 0.6,
        "close_vs_ema20": 0.02,
    }
    return SignalRecord(
        signal_id=f"sig_{ticker}_{s_date.isoformat()}",
        ticker=ticker,
        signal_date=s_date,
        signal="BUY",
        entry_low=entry_low,
        entry_high=entry_high,
        tp_price=tp_price,
        sl_price=sl_price,
        max_holding_days=max_holding_days,
        predicted_probability=prob,
        expected_return=exp_ret,
        score=score,
        model_version="v1.0.0_lightgbm",
        feature_version="v1.0.0",
        signal_config_version="v1.0.0",
        feature_snapshot=snap,
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Formatter Tests
# ---------------------------------------------------------------------------


def test_format_daily_signals_section_42_exact_spec():
    signal = _sample_signal()
    market = {"ihsg": "Bullish", "breadth": "Positive", "volatility": "Normal"}
    output = format_daily_signals([signal], target_date=date(2026, 10, 6), market_summary=market)

    assert "🤖 DAILY STOCK SIGNAL" in output
    assert "06 Oct 2026" in output
    assert "MARKET" in output
    assert "IHSG       : Bullish" in output
    assert "Breadth    : Positive" in output
    assert "Volatility : Normal" in output
    assert "━━━━━━━━━━━━━━━━" in output
    assert "🥇 ANTM" in output
    assert "Score           : 91/100" in output
    assert "P(TP before SL) : 74%" in output
    assert "Expected Return : +3.8%" in output
    assert "Entry           : 3,950–4,000" in output
    assert "TP              : +5%" in output
    assert "SL              : -2%" in output
    assert "Max Hold        : 10D" in output
    assert "Why:" in output
    assert "• strong momentum" in output
    assert "• volume expansion" in output
    assert "• sector outperforming" in output
    assert "• market regime supportive" in output


def test_format_daily_signals_empty_signals():
    output = format_daily_signals([], target_date=date(2026, 10, 12))
    assert "🤖 DAILY STOCK SIGNAL" in output
    assert "12 Oct 2026" in output
    assert "No BUY signals qualified for today." in output


def test_format_daily_signals_multiple_candidates():
    signals = [
        _sample_signal("ANTM", score=91.0),
        _sample_signal("BBCA", score=85.0),
        _sample_signal("BBRI", score=80.0),
        _sample_signal("TLKM", score=75.0),
    ]
    output = format_daily_signals(signals, target_date=date(2026, 10, 6))

    assert "🥇 ANTM" in output
    assert "🥈 BBCA" in output
    assert "🥉 BBRI" in output
    assert "4. TLKM" in output


def test_format_daily_signals_edge_cases():
    # Signal with None expected return and equal entry band
    sig = _sample_signal(
        ticker="INCO",
        exp_ret=None,
        entry_low=4000.0,
        entry_high=4000.0,
        tp_price=4200.0,
        sl_price=3920.0,
        snapshot={},
    )
    output = format_daily_signals([sig])
    assert "Expected Return : N/A" in output
    assert "Entry           : 4,000" in output
    assert "Why:" in output


def test_format_pct_helper():
    assert _format_pct(5.0) == "+5%"
    assert _format_pct(-2.0) == "-2%"
    assert _format_pct(3.8) == "+3.8%"
    assert _format_pct(0.0) == "0%"


def test_derive_rationale_fallback():
    # Empty snapshot returns at least 2 safe rationales
    reasons = derive_rationale({})
    assert len(reasons) >= 2
    assert all(isinstance(r, str) for r in reasons)


# ---------------------------------------------------------------------------
# Security & Token Masking Tests (Section 76)
# ---------------------------------------------------------------------------


def test_mask_token_utility():
    assert mask_token("123456789:ABCDEF123456") == "1234...3456"
    assert mask_token("short") == "***"
    assert mask_token("") == "[NOT_SET]"
    assert mask_token(None) == "[NOT_SET]"


def test_telegram_client_token_masking_in_repr_and_str():
    token = "987654321:SECRET_TOKEN_HERE"
    client = TelegramClient(bot_token=token, chat_id="12345678")

    rep = repr(client)
    str_rep = str(client)

    assert token not in rep
    assert "9876...HERE" in rep
    assert token not in str_rep


def test_telegram_client_token_masking_in_exceptions():
    token = "SECRET_123456789_SECRET"
    client = TelegramClient(bot_token=token, chat_id="12345678", max_retries=1)

    with patch("urllib.request.urlopen") as mock_url:
        mock_url.side_effect = urllib.error.URLError(f"Connection refused to {token}")
        with pytest.raises(TelegramError) as exc_info:
            client.send_message("Hello")

        err_msg = str(exc_info.value)
        assert token not in err_msg
        assert "SECR...CRET" in err_msg


# ---------------------------------------------------------------------------
# Client & Dispatcher Tests (Mocked Network)
# ---------------------------------------------------------------------------


def test_telegram_client_send_message_success():
    client = TelegramClient(bot_token="test_bot_token", chat_id="test_chat_id")

    mock_resp = MagicMock()
    mock_payload = json.dumps({"ok": True, "result": {"message_id": 999}})
    mock_resp.read.return_value = mock_payload.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        res = client.send_message("Test message")
        assert res["ok"] is True
        assert res["result"]["message_id"] == 999

        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.headers["Content-type"] == "application/json"
        data = json.loads(req.data.decode("utf-8"))
        assert data["chat_id"] == "test_chat_id"
        assert data["text"] == "Test message"


def test_telegram_client_missing_credentials():
    client_no_token = TelegramClient(bot_token="", chat_id="123")
    with pytest.raises(TelegramError, match="TELEGRAM_BOT_TOKEN is not configured"):
        client_no_token.send_message("Test")

    client_no_chat = TelegramClient(bot_token="tok", chat_id="")
    with pytest.raises(TelegramError, match="TELEGRAM_CHAT_ID is not configured"):
        client_no_chat.send_message("Test")


def test_telegram_client_bounded_retries_transient_failure():
    client = TelegramClient(bot_token="test_token", chat_id="123", max_retries=3)

    mock_resp = MagicMock()
    mock_payload = json.dumps({"ok": True, "result": {"message_id": 1}})
    mock_resp.read.return_value = mock_payload.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    # Fail twice with URLError, then succeed on 3rd attempt
    with (
        patch(
            "urllib.request.urlopen",
            side_effect=[
                urllib.error.URLError("Temporary DNS fail"),
                urllib.error.URLError("Socket timeout"),
                mock_resp,
            ],
        ),
        patch("time.sleep") as mock_sleep,
    ):
        res = client.send_message("Test retry")
        assert res["ok"] is True
        assert mock_sleep.call_count == 2


def test_telegram_client_fail_fast_on_4xx():
    client = TelegramClient(bot_token="test_token", chat_id="123", max_retries=3)

    http_err = urllib.error.HTTPError(
        url="http://test",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=io.BytesIO(b'{"ok": false, "description": "Chat not found"}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_err), patch("time.sleep") as mock_sleep:
        with pytest.raises(TelegramError, match="HTTP 400"):
            client.send_message("Test fail fast")
        # Should not sleep or retry on 400
        assert mock_sleep.call_count == 0


def test_telegram_client_broadcast_daily_signals():
    client = TelegramClient(bot_token="test_token", chat_id="123")
    signals = [_sample_signal("ANTM")]

    with patch.object(client, "send_message", return_value={"ok": True}) as mock_send:
        res = client.broadcast_daily_signals(signals)
        assert res["ok"] is True
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[1]["text"]
        assert "ANTM" in sent_text


# ---------------------------------------------------------------------------
# Decoupled Bot Command Dispatcher Tests (Rules 1 & 2)
# ---------------------------------------------------------------------------


def test_bot_dispatcher_help_and_start():
    dispatcher = TelegramBotDispatcher(signal_repo=MagicMock(), model_registry=MagicMock())

    help_out = dispatcher.dispatch("/help")
    assert "Available commands:" in help_out
    assert "/daily" in help_out
    assert "/signals" in help_out
    assert "/model" in help_out

    start_out = dispatcher.dispatch("/start")
    assert start_out == help_out


def test_bot_dispatcher_daily_delegation(tmp_path):
    db_file = tmp_path / "test_bot.db"
    sig_repo = SignalRepository(f"sqlite:///{db_file.as_posix()}")
    sig_repo.save_signals([_sample_signal("ANTM")])

    dispatcher = TelegramBotDispatcher(signal_repo=sig_repo, model_registry=MagicMock())
    resp = dispatcher.dispatch("/daily")

    assert "🤖 DAILY STOCK SIGNAL" in resp
    assert "ANTM" in resp


def test_bot_dispatcher_daily_empty_database(tmp_path):
    db_file = tmp_path / "empty.db"
    sig_repo = SignalRepository(f"sqlite:///{db_file.as_posix()}")

    dispatcher = TelegramBotDispatcher(signal_repo=sig_repo, model_registry=MagicMock())
    resp = dispatcher.dispatch("/daily")

    assert "No signals found in database" in resp


def test_bot_dispatcher_daily_specific_date_formats(tmp_path):
    db_file = tmp_path / "dates.db"
    sig_repo = SignalRepository(f"sqlite:///{db_file.as_posix()}")
    sig_old = _sample_signal("ANTM", s_date=date(2026, 10, 9))
    sig_new = _sample_signal("BBCA", s_date=date(2026, 10, 22))
    sig_repo.save_signals([sig_old, sig_new])

    dispatcher = TelegramBotDispatcher(signal_repo=sig_repo, model_registry=MagicMock())

    # 1. DD/MM/YY (e.g. 9/10/26)
    resp1 = dispatcher.dispatch("/daily 9/10/26")
    assert "09 Oct 2026" in resp1
    assert "ANTM" in resp1
    assert "BBCA" not in resp1

    # 2. DD/MM/YYYY (e.g. 09/10/2026)
    resp2 = dispatcher.dispatch("/daily 09/10/2026")
    assert "09 Oct 2026" in resp2
    assert "ANTM" in resp2

    # 3. YYYY-MM-DD (e.g. 2026-10-09)
    resp3 = dispatcher.dispatch("/daily 2026-10-09")
    assert "09 Oct 2026" in resp3

    # 4. DD-MM-YY (e.g. 9-10-26)
    resp4 = dispatcher.dispatch("/daily 9-10-26")
    assert "09 Oct 2026" in resp4

    # 5. Invalid date format
    resp_inv = dispatcher.dispatch("/daily bukan_tanggal")
    assert "Format tanggal tidak valid" in resp_inv

    # 6. Date with no recorded signals
    resp_nf = dispatcher.dispatch("/daily 01/01/26")
    assert "Tidak ada sinyal tercatat untuk tanggal `01/01/2026`" in resp_nf
    assert "Tanggal sinyal terbaru yang tersedia" in resp_nf


def test_bot_dispatcher_signals_command(tmp_path):
    db_file = tmp_path / "signals.db"
    sig_repo = SignalRepository(f"sqlite:///{db_file.as_posix()}")
    sig_repo.save_signals([_sample_signal("ANTM"), _sample_signal("BBCA")])

    dispatcher = TelegramBotDispatcher(signal_repo=sig_repo, model_registry=MagicMock())
    resp = dispatcher.dispatch("/signals 2")

    assert "Recent Signals" in resp
    assert "ANTM" in resp
    assert "BBCA" in resp
    assert "ID:" in resp


def test_bot_dispatcher_model_command(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path / "registry")
    meta = ModelMetadata(
        model_version="v1.0.0_lightgbm",
        algorithm="LightGBMClassifier",
        training_start="2025-01-01",
        training_end="2026-06-30",
        metrics={"roc_auc": 0.62, "accuracy": 0.58},
        status="champion",
        feature_names=["f1", "f2"],
    )
    registry.save_model("DUMMY_MODEL_OBJ", meta)

    dispatcher = TelegramBotDispatcher(signal_repo=MagicMock(), model_registry=registry)
    resp = dispatcher.dispatch("/model")

    assert "Champion 🏆" in resp
    assert "v1.0.0_lightgbm" in resp
    assert "LightGBMClassifier" in resp
    assert "`roc_auc`: 0.6200" in resp


def test_bot_dispatcher_unknown_command():
    dispatcher = TelegramBotDispatcher(signal_repo=MagicMock(), model_registry=MagicMock())
    resp = dispatcher.dispatch("/unknown_command")
    assert "Unknown command `/unknown_command`" in resp
    assert "/help" in resp


def test_derive_rationale_handles_none_and_invalid_values():
    # Pass snapshot containing None values and bad types; should not raise TypeError
    bad_snapshot = {
        "return_5d": None,
        "close_vs_ema20": None,
        "rsi14": None,
        "volume_ratio_20d": None,
        "volume_ratio_5d": None,
        "rel_strength_sector_20d": None,
        "rel_strength_ihsg_20d": None,
        "market_breadth": None,
        "ihsg_vs_ema20": None,
        "atr_pct": None,
        "corrupt": "invalid",
    }
    reasons = derive_rationale(bad_snapshot)
    assert isinstance(reasons, list)
    assert len(reasons) >= 2


def test_derive_market_summary_case_insensitive_and_none():
    # Uppercase keys
    ihsg, breadth, vol = _derive_market_summary(
        {}, {"IHSG": "Bullish", "BREADTH": "Positive", "VOLATILITY": "Low"}
    )
    assert ihsg == "Bullish"
    assert breadth == "Positive"
    assert vol == "Low"

    # None values in snapshot fallback cleanly
    ihsg2, breadth2, vol2 = _derive_market_summary(
        {"ihsg_vs_ema20": None, "market_breadth": None, "market_volatility": None}, None
    )
    assert ihsg2 == "Neutral"
    assert breadth2 == "Neutral"
    assert vol2 == "Normal"


def test_split_message_utility():
    short_text = "Short message"
    assert split_message(short_text, max_chars=100) == [short_text]

    # Large text with dividers
    block = "Block of text here\n" * 20
    big_text = f"{block}\n\n━━━━━━━━━━━━━━━━\n\n{block}\n\n━━━━━━━━━━━━━━━━\n\n{block}"
    chunks = split_message(big_text, max_chars=len(block) + 50)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= len(block) + 50


def test_telegram_client_send_message_chunked_delivery():
    client = TelegramClient(bot_token="test_bot_token", chat_id="123")
    oversized_text = ("Line of stock info\n" * 100 + "\n\n━━━━━━━━━━━━━━━━\n\n") * 5

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 10}}).encode(
        "utf-8"
    )
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        res = client.send_message(oversized_text)
        assert res["ok"] is True
        assert mock_urlopen.call_count >= 2
        assert res.get("chunks_sent", 1) >= 2


def test_telegram_client_http_429_adaptive_retry():
    client = TelegramClient(bot_token="test_token", chat_id="123", max_retries=2)

    headers = {"Retry-After": "1.5"}
    body_429 = (
        b'{"ok": false, "error_code": 429, "description": "Too Many Requests", '
        b'"parameters": {"retry_after": 2}}'
    )
    http_429 = urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Too Many Requests",
        hdrs=headers,
        fp=io.BytesIO(body_429),
    )

    mock_success = MagicMock()
    mock_success.read.return_value = json.dumps({"ok": True, "result": {"message_id": 99}}).encode(
        "utf-8"
    )
    mock_success.__enter__.return_value = mock_success

    with (
        patch("urllib.request.urlopen", side_effect=[http_429, mock_success]),
        patch("time.sleep") as mock_sleep,
    ):
        res = client.send_message("Test 429")
        assert res["ok"] is True
        mock_sleep.assert_called_once_with(1.5)


def test_telegram_client_markdown_parse_fallback():
    client = TelegramClient(bot_token="test_token", chat_id="123", max_retries=2)

    body_parse_err = b'{"ok": false, "description": "Bad Request: can\'t parse entities"}'
    http_parse_err = urllib.error.HTTPError(
        url="http://test",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=io.BytesIO(body_parse_err),
    )

    mock_success = MagicMock()
    mock_success.read.return_value = json.dumps({"ok": True, "result": {"message_id": 105}}).encode(
        "utf-8"
    )
    mock_success.__enter__.return_value = mock_success

    with patch(
        "urllib.request.urlopen", side_effect=[http_parse_err, mock_success]
    ) as mock_urlopen:
        res = client.send_message("Unescaped * text")
        assert res["ok"] is True
        # Second call should have parse_mode=None (fallback to plaintext)
        second_call_req = mock_urlopen.call_args_list[1][0][0]
        data = json.loads(second_call_req.data.decode("utf-8"))
        assert "parse_mode" not in data


def test_bot_dispatcher_compare_positions_performance(tmp_path):
    registry = ModelRegistry(registry_dir=tmp_path / "registry")
    meta1 = ModelMetadata(
        model_version="v1.0.0_lightgbm",
        algorithm="LightGBMClassifier",
        training_start="2025-01-01",
        training_end="2026-06-30",
        metrics={"roc_auc": 0.62},
        status="champion",
    )
    meta2 = ModelMetadata(
        model_version="v1.0.1_logistic",
        algorithm="LogisticRegression",
        training_start="2025-01-01",
        training_end="2026-06-30",
        metrics={"roc_auc": 0.60},
        status="challenger",
    )
    registry.save_model("M1", meta1)
    registry.save_model("M2", meta2)

    dispatcher = TelegramBotDispatcher(signal_repo=MagicMock(), model_registry=registry)

    comp_out = dispatcher.dispatch("/compare")
    assert "Model Comparison" in comp_out
    assert "v1.0.0_lightgbm" in comp_out

    pos_out = dispatcher.dispatch("/positions")
    assert "Phase 8" in pos_out

    perf_out = dispatcher.dispatch("/performance")
    assert "Phase 9" in perf_out


def test_telegram_client_ssl_cert_verification_fallback():
    client = TelegramClient(bot_token="test_token", chat_id="123")

    cert_error = urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    mock_success = MagicMock()
    success_data = json.dumps({"ok": True, "result": {"message_id": 200}}).encode("utf-8")
    mock_success.read.return_value = success_data
    mock_success.__enter__.return_value = mock_success

    with patch("urllib.request.urlopen", side_effect=[cert_error, mock_success]) as mock_urlopen:
        res = client.send_message("Test SSL fallback")
        assert res["ok"] is True
        assert mock_urlopen.call_count == 2
        # Verify second call passed an unverified SSL context
        _, kwargs = mock_urlopen.call_args_list[1]
        assert "context" in kwargs


def test_telegram_commands_definition_and_validation():
    cmds = get_bot_commands()
    assert len(cmds) >= 10
    cmd_names = [c["command"] for c in cmds]
    assert "start" in cmd_names
    assert "help" in cmd_names
    assert "menu" in cmd_names
    assert "daily" in cmd_names
    assert "signals" in cmd_names
    assert "status" in cmd_names
    assert "pipeline" in cmd_names
    assert "portfolio" in cmd_names
    assert "positions" in cmd_names

    # Check validation rules
    valid = validate_bot_commands([
        {"command": "/test", "description": "A test command"},
        {"command": "TEST_TWO", "description": "Another test"},
    ])
    assert valid[0]["command"] == "test"
    assert valid[1]["command"] == "test_two"

    with pytest.raises(ValueError):
        validate_bot_commands([{"command": "invalid space", "description": "fail"}])


def test_format_commands_for_botfather():
    out = format_commands_for_botfather([
        {"command": "start", "description": "Start bot"},
        {"command": "help", "description": "Show help"},
    ])
    assert "start - Start bot" in out
    assert "help - Show help" in out


def test_telegram_client_set_my_commands():
    client = TelegramClient(bot_token="test_token", chat_id="123")
    mock_success = MagicMock()
    mock_success.read.return_value = json.dumps({"ok": True, "result": True}).encode("utf-8")
    mock_success.__enter__.return_value = mock_success

    with patch("urllib.request.urlopen", return_value=mock_success) as mock_urlopen:
        res = client.set_my_commands(scope={"type": "default"}, language_code="en")
        assert res["ok"] is True
        req = mock_urlopen.call_args[0][0]
        assert "setMyCommands" in req.full_url
        data = json.loads(req.data.decode("utf-8"))
        assert "commands" in data
        assert isinstance(data["commands"], list)
        assert data["scope"] == {"type": "default"}
        assert data["language_code"] == "en"


def test_telegram_client_get_and_delete_my_commands():
    client = TelegramClient(bot_token="test_token", chat_id="123")
    mock_get = MagicMock()
    mock_get.read.return_value = json.dumps(
        {"ok": True, "result": [{"command": "start", "description": "desc"}]}
    ).encode("utf-8")
    mock_get.__enter__.return_value = mock_get

    mock_del = MagicMock()
    mock_del.read.return_value = json.dumps({"ok": True, "result": True}).encode("utf-8")
    mock_del.__enter__.return_value = mock_del

    with patch("urllib.request.urlopen", side_effect=[mock_get, mock_del]):
        get_res = client.get_my_commands()
        assert get_res["ok"] is True
        assert len(get_res["result"]) == 1

        del_res = client.delete_my_commands()
        assert del_res["ok"] is True


def test_bot_dispatcher_handles_status_pipeline_portfolio(tmp_path):
    dispatcher = TelegramBotDispatcher(signal_repo=MagicMock(), model_registry=MagicMock())

    # Help includes new commands
    help_out = dispatcher.dispatch("/help")
    assert "/status" in help_out
    assert "/pipeline" in help_out
    assert "/portfolio" in help_out

    # Status returns string
    status_out = dispatcher.dispatch("/status")
    assert "Operational & Pipeline Status" in status_out

    # Pipeline returns status or informative message
    pipe_out = dispatcher.dispatch("/pipeline")
    assert "Daily Pipeline Run Summary" in pipe_out or "No pipeline run report found" in pipe_out

    # Portfolio delegates to positions
    port_out = dispatcher.dispatch("/portfolio")
    assert "positions" in port_out.lower() or "journal" in port_out.lower()

    # Typing '/' directly renders interactive command menu
    slash_out = dispatcher.dispatch("/")
    assert "Available commands:" in slash_out
    assert "/daily" in slash_out
    assert "/status" in slash_out

    # Typing '/menu' displays available options
    menu_out = dispatcher.dispatch("/menu")
    assert "Available commands:" in menu_out
    assert "/pipeline" in menu_out

