import json
import subprocess
import sys
from unittest.mock import MagicMock, patch

from python.common.types import SignalConfig
from python.data.provider import MockMarketDataProvider
from python.data.repository import DailyBarRepository
from python.models.baseline import LogisticRegressionBaseline
from python.models.registry import ModelMetadata, ModelRegistry
from python.signals.engine import SignalEngine
from python.signals.repository import SignalRepository
from services.telegram.bot import TelegramBotDispatcher
from services.telegram.client import TelegramClient
from services.telegram.formatter import format_daily_signals


def test_telegram_pipeline_end_to_end(tmp_path):
    # 1. Setup mock SQLite DB and model registry
    db_file = tmp_path / "integration_telegram.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    reg_dir = tmp_path / "model_registry"

    bar_repo = DailyBarRepository(db_url)
    sig_repo = SignalRepository(db_url)
    model_reg = ModelRegistry(reg_dir)

    universe = ["ANTM", "BBCA"]
    mock_provider = MockMarketDataProvider(universe=universe, days=100)
    for t in universe:
        bars = mock_provider.get_daily_bars(t)
        bar_repo.save_bars(bars)

    # 2. Register champion model
    champion_model = LogisticRegressionBaseline()
    champion_model.fit(
        X=[[0.05, 1.5, 0.02], [-0.05, 0.8, -0.02]],
        y=[1, 0],
        feature_names=["return_5d", "volume_ratio_20d", "close_vs_ema20"],
    )
    meta = ModelMetadata(
        model_version="v1.0.0_champion_test",
        algorithm="LogisticRegressionBaseline",
        training_start="2025-01-01",
        training_end="2026-06-30",
        metrics={"accuracy": 0.65, "f1": 0.60},
        status="champion",
        feature_names=["return_5d", "volume_ratio_20d", "close_vs_ema20"],
    )
    model_reg.save_model(champion_model, meta)

    # 3. Generate signals using SignalEngine
    target_date = bar_repo.get_latest_date("ANTM")
    assert target_date is not None

    cfg = SignalConfig(top_n=2, min_probability=0.30)
    engine = SignalEngine(
        config=cfg,
        model_registry=model_reg,
        bar_repo=bar_repo,
    )
    bars_by_ticker = {t: bar_repo.get_daily_bars(t) for t in universe}

    signals = engine.generate_signals(
        signal_date=target_date,
        universe=universe,
        use_champion=True,
        bars_by_ticker=bars_by_ticker,
    )
    assert len(signals) > 0

    # Persist signals to repository
    saved_cnt = sig_repo.save_signals(signals)
    assert saved_cnt == len(signals)

    # 4. Pure Formatter verification
    formatted = format_daily_signals(signals, target_date=target_date)
    assert "🤖 DAILY STOCK SIGNAL" in formatted
    assert target_date.strftime("%d %b %Y") in formatted
    assert "MARKET" in formatted
    assert "🥇" in formatted
    assert "Why:" in formatted

    # 5. Client Mock Dispatch
    client = TelegramClient(
        bot_token="bot_123456789:ABC_TOKEN",
        chat_id="-100987654321",
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {
            "ok": True,
            "result": {
                "message_id": 101,
                "chat": {"id": -100987654321, "title": "BEI Signals Channel"},
                "text": formatted,
            },
        }
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        dispatch_res = client.broadcast_daily_signals(signals)
        assert dispatch_res["ok"] is True
        assert dispatch_res["result"]["message_id"] == 101

        # Check outbound HTTP request payload
        req = mock_urlopen.call_args[0][0]
        sent_payload = json.loads(req.data.decode("utf-8"))
        assert sent_payload["chat_id"] == "-100987654321"
        assert sent_payload["parse_mode"] == "Markdown"
        assert sent_payload["disable_web_page_preview"] is True
        assert "🤖 DAILY STOCK SIGNAL" in sent_payload["text"]

    # 6. Bot Dispatcher Commands
    bot = TelegramBotDispatcher(signal_repo=sig_repo, model_registry=model_reg)

    daily_out = bot.dispatch("/daily")
    assert "🤖 DAILY STOCK SIGNAL" in daily_out
    assert signals[0].ticker in daily_out

    signals_out = bot.dispatch("/signals")
    assert "📋 *Recent Signals" in signals_out
    assert signals[0].ticker in signals_out

    model_out = bot.dispatch("/model")
    assert "Champion 🏆" in model_out
    assert "v1.0.0_champion_test" in model_out

    # 7. CLI Dry-run script execution
    cmd = [
        sys.executable,
        "-m",
        "scripts.send_daily_telegram",
        "--db-url",
        db_url,
        "--date",
        target_date.isoformat(),
        "--dry-run",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
    assert proc.returncode == 0
    assert "🤖 DAILY STOCK SIGNAL" in proc.stdout
    assert signals[0].ticker in proc.stdout

    # 8. CLI Mutual Exclusion and validation checks
    cmd_conflict = [
        sys.executable,
        "-m",
        "scripts.send_daily_telegram",
        "--generate",
        "--use-champion",
        "--model-version",
        "custom_v1",
    ]
    proc_conflict = subprocess.run(cmd_conflict, capture_output=True, text=True, encoding="utf-8")
    assert proc_conflict.returncode != 0
    assert "Cannot specify both --use-champion and --model-version" in proc_conflict.stderr

    cmd_bad_n = [
        sys.executable,
        "-m",
        "scripts.send_daily_telegram",
        "--top-n",
        "0",
    ]
    proc_bad_n = subprocess.run(cmd_bad_n, capture_output=True, text=True, encoding="utf-8")
    assert proc_bad_n.returncode != 0
    assert "--top-n must be at least 1" in proc_bad_n.stderr
