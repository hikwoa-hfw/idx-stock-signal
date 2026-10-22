import json
import math
from datetime import date
from pathlib import Path
from typing import Optional

from python.common.types import get_bei_tick_size
from python.config.settings import PROJECT_ROOT
from python.data.repository import DailyBarRepository
from python.journal.service import PositionJournalService
from python.models.registry import ModelRegistry
from python.signals.repository import SignalRepository
from services.telegram.formatter import format_daily_signals


class TelegramBotDispatcher:
    """Decoupled Telegram bot command dispatcher.

    Strict adherence to Rule 1 & Rule 2:
    - Zero ML indicator calculation or model inference in command handlers.
    - Handlers only query SignalRepository, ModelRegistry, and application services.
    """

    # ponytail: synchronous dispatcher; add long-polling/webhook daemon when cloud-hosted.
    def __init__(
        self,
        signal_repo: Optional[SignalRepository] = None,
        model_registry: Optional[ModelRegistry] = None,
        journal_service: Optional[PositionJournalService] = None,
        bar_repo: Optional[DailyBarRepository] = None,
    ) -> None:
        self.signal_repo = signal_repo or SignalRepository()
        self.model_registry = model_registry or ModelRegistry()
        self.bar_repo = bar_repo
        self.journal_service = journal_service or PositionJournalService(
            bar_repo=self.bar_repo or DailyBarRepository()
        )

    def dispatch(self, message_text: str) -> str:
        """Route incoming message text to appropriate command handler."""
        clean_text = (message_text or "").strip()
        if not clean_text:
            return self.handle_help()

        parts = clean_text.split()
        command = parts[0].lower().split("@")[0]  # strip bot handle e.g. /daily@stockbot
        args = parts[1:]

        if command in ("/start", "/help"):
            return self.handle_help()
        elif command == "/daily":
            return self.handle_daily(args)
        elif command == "/signals":
            return self.handle_signals(args)
        elif command == "/status":
            return self.handle_status(args)
        elif command == "/pipeline":
            return self.handle_pipeline(args)
        elif command in ("/positions", "/portfolio"):
            return self.handle_positions(args)
        elif command == "/enter":
            return self.handle_enter(args)
        elif command == "/exit":
            return self.handle_exit(args)
        elif command == "/cancel":
            return self.handle_cancel(args)
        elif command == "/model":
            return self.handle_model(args)
        elif command == "/compare":
            return self.handle_compare(args)
        elif command == "/performance":
            return self.handle_performance(args)
        else:
            return self.handle_unknown(command)

    def handle_help(self) -> str:
        return (
            "🤖 *BEI Daily Stock Signal Bot*\n\n"
            "Available commands:\n"
            "• `/daily` — Latest ranked daily buy signals\n"
            "• `/signals [N]` — Recent trading signal IDs and summary\n"
            "• `/status` — Pipeline & paper trading observation status\n"
            "• `/pipeline` — Latest daily pipeline run summary\n"
            "• `/portfolio` or `/positions` — Open positions and unrealized PnL\n"
            "• `/enter <TICKER> <PRICE> <QTY> [SIGNAL_ID]` — Open manual position\n"
            "• `/exit <TICKER_OR_ID> <PRICE> [REASON]` — Close position (TP/SL/MANUAL)\n"
            "• `/cancel <TICKER_OR_ID> [REASON]` — Cancel open position\n"
            "• `/model` — Champion model version and evaluation metrics\n"
            "• `/compare` — Compare model versions in registry\n"
            "• `/performance` — Out-of-sample performance metrics\n"
            "• `/help` — Show command instructions"
        )

    def handle_daily(self, args: Optional[list[str]] = None) -> str:
        distinct_dates = self.signal_repo.get_distinct_dates()
        if not distinct_dates:
            return (
                "ℹ️ No signals found in database.\n"
                "Run the signal generation pipeline first (`python -m scripts.generate_signals`)."
            )

        target_date: date = distinct_dates[-1]
        signals = self.signal_repo.get_signals(signal_date=target_date)
        return format_daily_signals(signals=signals, target_date=target_date, dual_mode=True)

    def handle_signals(self, args: Optional[list[str]] = None) -> str:
        limit = 5
        if args and args[0].isdigit():
            limit = min(int(args[0]), 20)

        signals = self.signal_repo.get_signals(limit=limit)
        if not signals:
            return "ℹ️ No recent signals recorded."

        lines = [f"📋 *Recent Signals (Latest {len(signals)})*:\n"]
        for s in signals:
            ret_str = f"{s.expected_return * 100:+.1f}%" if s.expected_return is not None else "N/A"
            short_id = s.signal_id[:8] if len(s.signal_id) > 8 else s.signal_id
            if s.entry_low < s.entry_high:
                low_str = f"{s.entry_low:,.0f}"
                high_str = f"{s.entry_high:,.0f}"
                if low_str == high_str:
                    tick = get_bei_tick_size(s.entry_low)
                    low_d = math.floor(s.entry_low / tick) * tick
                    high_d = math.ceil(s.entry_high / tick) * tick
                    if low_d >= high_d:
                        low_d = max(1.0, low_d - tick)
                        high_d = high_d + tick
                    entry_str = f"{low_d:,.0f}–{high_d:,.0f}"
                else:
                    entry_str = f"{low_str}–{high_str}"
            else:
                tick = get_bei_tick_size(s.entry_low)
                low_d = max(1.0, s.entry_low - tick)
                high_d = s.entry_low + tick
                entry_str = f"{low_d:,.0f}–{high_d:,.0f}"

            status_str = getattr(s, "status", None) or s.signal or "BUY"
            ref_str = (
                f" | Ref: {s.reference_price:,.0f}"
                if getattr(s, "reference_price", None) is not None
                else ""
            )
            hdr = f"• *{s.ticker}* ({s.signal_date}) [{status_str}]"
            meta = (
                f"ID: `{short_id}` | Score: {s.score:.0f} | "
                f"P: {s.predicted_probability * 100:.0f}% | Exp: {ret_str}{ref_str}"
            )
            lines.append(
                f"{hdr} | {meta}\n"
                f"  Entry: {entry_str} | "
                f"TP: {s.tp_price:,.0f} | SL: {s.sl_price:,.0f}"
            )
        return "\n".join(lines)

    def handle_model(self, args: Optional[list[str]] = None) -> str:
        low_champ = self.model_registry.get_champion(task="classification", mode="LOW_PRICE")
        high_champ = self.model_registry.get_champion(task="classification", mode="HIGHER_PRICE")
        legacy_champ = self.model_registry.get_champion(task="classification")

        if low_champ or high_champ:
            lines = ["🧠 *Model Registry (Dual-Mode)*\n"]
            if low_champ:
                _, m = low_champ
                m_items = sorted(m.metrics.items())[:3]
                metric_str = ", ".join(f"`{k}`: {v:.4f}" for k, v in m_items) or "N/A"
                lines.append(
                    f"🏆 *Champion [LOW_PRICE]*: `{m.model_version}` ({m.algorithm})\n"
                    f"  Metrics: {metric_str}"
                )
            else:
                lines.append("• *LOW_PRICE*: No champion promoted yet")

            if high_champ:
                _, m = high_champ
                m_items = sorted(m.metrics.items())[:3]
                metric_str = ", ".join(f"`{k}`: {v:.4f}" for k, v in m_items) or "N/A"
                lines.append(
                    f"\n🏆 *Champion [HIGHER_PRICE]*: `{m.model_version}` ({m.algorithm})\n"
                    f"  Metrics: {metric_str}"
                )
            else:
                lines.append("\n• *HIGHER_PRICE*: No champion promoted yet")
            return "\n".join(lines)

        if legacy_champ is None:
            all_models = self.model_registry.list_models()
            if not all_models:
                return "ℹ️ No models registered in model registry."
            meta = all_models[0]
            status_text = "Challenger (No Champion Promoted)"
        else:
            _, meta = legacy_champ
            status_text = "Champion 🏆"

        lines = [
            "🧠 *Model Information*",
            f"Status       : {status_text}",
            f"Version      : `{meta.model_version}`",
            f"Algorithm    : {meta.algorithm}",
            f"Task         : {meta.task}",
            f"Features     : {len(meta.feature_names)} features",
            f"Trained End  : {meta.training_end}",
        ]
        if meta.metrics:
            lines.append("\n*Metrics:*")
            for k, v in sorted(meta.metrics.items()):
                val_str = f"{v:.4f}" if isinstance(v, float) else f"{v}"
                lines.append(f"• `{k}`: {val_str}")

        return "\n".join(lines)

    def handle_compare(self, args: Optional[list[str]] = None) -> str:
        models = self.model_registry.list_models()
        if not models:
            return "ℹ️ No models found in registry to compare."

        if len(models) == 1:
            return (
                f"ℹ️ Only 1 model registered: `{models[0].model_version}` ({models[0].status}). "
                "Train another model to enable comparisons."
            )

        # If specific versions provided
        if args and len(args) >= 2:
            v1_str, v2_str = args[0], args[1]
            try:
                m1 = self.model_registry.get_metadata(v1_str)
                m2 = self.model_registry.get_metadata(v2_str)
                cand_list = [m1, m2]
            except FileNotFoundError as err:
                return f"⚠️ Model comparison error: {err}"
        else:
            cand_list = models[:2]

        lines = ["⚖️ *Model Comparison*:\n"]
        for m in cand_list:
            champ_badge = "🏆 Champion" if m.status.lower() == "champion" else "Challenger"
            metric_str = ", ".join(f"`{k}`: {v:.4f}" for k, v in sorted(m.metrics.items())[:3])
            lines.append(
                f"• `{m.model_version}` ({champ_badge})\n"
                f"  Algorithm: {m.algorithm} | Metrics: {metric_str or 'N/A'}"
            )
        return "\n".join(lines)

    def handle_enter(self, args: Optional[list[str]] = None) -> str:
        if not args or len(args) < 3:
            return (
                "ℹ️ *Usage*: `/enter <TICKER> <PRICE> <QTY> [SIGNAL_ID]`\n"
                "Example: `/enter BBCA 10000 100`\n"
                "Example: `/enter BBCA 10000 100 sig_20261012_bbca`"
            )
        ticker = args[0]
        try:
            price = float(args[1].replace(",", ""))
            qty = int(args[2].replace(",", ""))
        except ValueError:
            return "⚠️ Error: Price must be a valid number and quantity must be an integer."

        signal_id = args[3] if len(args) > 3 else None

        try:
            record = self.journal_service.open_position(
                ticker=ticker,
                entry_price=price,
                quantity=qty,
                signal_id=signal_id,
            )
            sig_line = f"\n• Signal ID: `{record.signal_id}`" if record.signal_id else ""
            return (
                "✅ *Position Opened*\n"
                f"• Ticker: *{record.ticker}*\n"
                f"• Entry Price: {record.actual_entry_price:,.2f}\n"
                f"• Quantity: {record.quantity:,}\n"
                f"• Date: {record.actual_entry_date}\n"
                f"• Position ID: `{record.position_id[:8]}`"
                f"{sig_line}"
            )
        except Exception as err:
            return f"⚠️ Failed to open position: {err}"

    def handle_exit(self, args: Optional[list[str]] = None) -> str:
        if not args or len(args) < 2:
            return (
                "ℹ️ *Usage*: `/exit <TICKER_OR_ID> <PRICE> [REASON]`\n"
                "Example: `/exit BBCA 10500 TP`\n"
                "Example: `/exit pos-12345678 10500 MANUAL`"
            )
        target = args[0]
        try:
            exit_price = float(args[1].replace(",", ""))
        except ValueError:
            return "⚠️ Error: Exit price must be a valid number."

        reason = args[2].upper() if len(args) > 2 else "MANUAL"

        try:
            record = self.journal_service.close_position(
                position_id_or_ticker=target,
                exit_price=exit_price,
                exit_reason=reason,
            )
            ret_pct = (
                f"{record.realized_return * 100:+.2f}%"
                if record.realized_return is not None
                else "0.00%"
            )
            hold_str = f"{record.holding_days}D" if record.holding_days is not None else "0D"
            return (
                "✅ *Position Closed*\n"
                f"• Ticker: *{record.ticker}*\n"
                f"• Exit Price: {record.actual_exit_price:,.2f}\n"
                f"• Realized Return: *{ret_pct}*\n"
                f"• Holding Days: {hold_str}\n"
                f"• Reason: {record.exit_reason}\n"
                f"• Position ID: `{record.position_id[:8]}`"
            )
        except Exception as err:
            return f"⚠️ Failed to close position: {err}"

    def handle_cancel(self, args: Optional[list[str]] = None) -> str:
        if not args or len(args) < 1:
            return (
                "ℹ️ *Usage*: `/cancel <TICKER_OR_ID> [REASON]`\nExample: `/cancel BBCA User aborted`"
            )
        target = args[0]
        reason = " ".join(args[1:]).strip() if len(args) > 1 else "CANCELLED"

        try:
            record = self.journal_service.cancel_position(
                position_id_or_ticker=target,
                reason=reason,
            )
            return (
                "🚫 *Position Cancelled*\n"
                f"• Ticker: *{record.ticker}*\n"
                f"• Position ID: `{record.position_id[:8]}`\n"
                f"• Notes: {record.notes or 'N/A'}"
            )
        except Exception as err:
            return f"⚠️ Failed to cancel position: {err}"

    def handle_positions(self, args: Optional[list[str]] = None) -> str:
        ticker_filter = args[0].strip().upper().removesuffix(".JK") if args else None
        open_positions = self.journal_service.get_open_positions(ticker=ticker_filter)
        if not open_positions:
            if ticker_filter:
                return f"ℹ️ No open positions found for '{ticker_filter}' in journal."
            return "ℹ️ No open positions in journal (Phase 8 position tracking)."

        filter_label = f" for {ticker_filter}" if ticker_filter else ""
        lines = [f"📊 *Open Positions{filter_label} ({len(open_positions)})*:\n"]
        for pos in open_positions:
            short_id = pos.position_id[:8] if len(pos.position_id) > 8 else pos.position_id
            _, ret_pct = self.journal_service.get_unrealized_pnl(pos)
            if ret_pct is not None:
                pnl_str = f" | PnL: *{ret_pct * 100:+.2f}%*"
            else:
                pnl_str = ""

            sig_str = f" | Sig: `{pos.signal_id[:8]}`" if pos.signal_id else ""
            lines.append(
                f"• *{pos.ticker}* (ID: `{short_id}`)\n"
                f"  Entry: {pos.actual_entry_price:,.2f} | Qty: {pos.quantity:,} | "
                f"Date: {pos.actual_entry_date}{pnl_str}{sig_str}"
            )
        return "\n".join(lines)

    def handle_performance(self, args: Optional[list[str]] = None) -> str:
        return (
            "ℹ️ Out-of-sample performance evaluation is scheduled for Phase 9.\n"
            "Live evaluation against realized market outcomes will be available in Phase 9."
        )

    def handle_status(self, args: Optional[list[str]] = None) -> str:
        """Show current operational pipeline and paper trading observation status."""
        lines = ["📡 *Operational & Pipeline Status*\n"]
        reports_dir = PROJECT_ROOT / "artifacts" / "pipeline_runs"
        reports_file = Path(reports_dir / "latest_pipeline_run.json")
        if reports_file.is_file():
            try:
                with open(reports_file, "r", encoding="utf-8") as f:
                    rep = json.load(f)
                run_id = rep.get("run_id", "N/A")
                status = rep.get("overall_status", "UNKNOWN")
                dt = rep.get("finished_at", rep.get("started_at", "N/A"))
                lines.append(f"• *Latest Pipeline Run*: `{status}`")
                lines.append(f"  Run ID: `{run_id}` | Time: {dt}")
                val_dt = rep.get("validation_summary", {}).get("latest_completed_session")
                cov = rep.get("validation_summary", {}).get("coverage_pct")
                if val_dt:
                    cov_str = f" ({cov:.1%})" if cov is not None else ""
                    lines.append(f"  Session: {val_dt}{cov_str}")
            except Exception:
                lines.append("• *Latest Pipeline Run*: Report unavailable")
        else:
            lines.append("• *Latest Pipeline Run*: No execution recorded yet")

        state_file = Path(PROJECT_ROOT / "artifacts" / "phase_11f" / "paper_trading_state.json")
        if state_file.is_file():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    st = json.load(f)
                appr = "APPROVED ✅" if st.get("user_approved") else "PENDING APPROVAL ⏳"
                cutoff = (
                    st.get("effective_observation_cutoff")
                    or st.get("approval_data_cutoff")
                    or "N/A"
                )
                eq = st.get("current_equity_idr", 100_000_000.0)
                cash = st.get("cash_balance_idr", 100_000_000.0)
                pos_cnt = len(st.get("open_positions", []))
                lines.append(f"\n• *Paper Trading*: {appr}")
                lines.append(f"  Effective Cutoff: {cutoff}")
                lines.append(f"  Equity: IDR {eq:,.2f} | Cash: IDR {cash:,.2f}")
                lines.append(f"  Open Positions: {pos_cnt}")
            except Exception:
                pass

        return "\n".join(lines)

    def handle_pipeline(self, args: Optional[list[str]] = None) -> str:
        """Display summary of the latest daily pipeline execution."""
        reports_dir = PROJECT_ROOT / "artifacts" / "pipeline_runs"
        reports_file = Path(reports_dir / "latest_pipeline_run.json")
        if not reports_file.is_file():
            return (
                "ℹ️ No pipeline run report found.\n"
                "Run the daily pipeline first (`python -m scripts.run_daily_pipeline`)."
            )
        try:
            with open(reports_file, "r", encoding="utf-8") as f:
                rep = json.load(f)
        except Exception as e:
            return f"⚠️ Failed to read pipeline report: {e}"

        status_emoji = "✅" if rep.get("overall_status") == "SUCCESS" else "ℹ️"
        lines = [
            f"{status_emoji} *Daily Pipeline Run Summary*\n",
            f"• *Status*: `{rep.get('overall_status', 'UNKNOWN')}`",
            f"• *Run ID*: `{rep.get('run_id', 'N/A')}`",
            f"• *Provider*: `{rep.get('configured_provider', 'N/A')}`",
            f"• *Duration*: {rep.get('duration_seconds', 0.0):.2f}s",
            f"• *Git SHA*: `{rep.get('git_commit_sha', 'UNKNOWN')[:8]}`",
        ]
        val = rep.get("validation_summary", {})
        if val:
            sess = val.get("latest_completed_session", "N/A")
            cov = val.get("coverage_pct")
            cov_str = f"{cov:.1%}" if cov is not None else "N/A"
            lines.append(f"• *Market Session*: {sess} (Coverage: {cov_str})")
        pt = rep.get("paper_trading_summary", {})
        if pt:
            pt_action = pt.get("action", "N/A")
            lines.append(f"• *Paper Trading*: `{pt_action}`")
            if pt.get("reason"):
                lines.append(f"  _{pt['reason']}_")
        return "\n".join(lines)

    def handle_unknown(self, command: str) -> str:
        return f"Unknown command `{command}`. Use `/help` to see available commands."
