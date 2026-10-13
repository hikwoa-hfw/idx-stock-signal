from datetime import date
from typing import Any, Optional, Sequence, Union

from python.common.types import SignalRecord


def _format_pct(val: float) -> str:
    """Format float percentage deterministically.

    Examples: 5.0 -> '+5%', -2.0 -> '-2%', 3.8 -> '+3.8%'
    """
    sign = "+" if val > 0 else ""
    if abs(val - round(val)) < 1e-4:
        return f"{sign}{int(round(val))}%"
    return f"{sign}{val:.1f}%"


def _safe_float(val: Any, default: float) -> float:
    """Extract finite float value with fallback to default."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if (f == f and f != float("inf") and f != float("-inf")) else default
    except (ValueError, TypeError):
        return default


def derive_rationale(snapshot: dict[str, Any]) -> list[str]:
    """Derives deterministic bulleted rationales from a feature snapshot."""
    reasons: list[str] = []

    # 1. Momentum
    ret5 = _safe_float(snapshot.get("return_5d"), 0.0)
    c_ema20 = _safe_float(snapshot.get("close_vs_ema20"), 0.0)
    rsi = _safe_float(snapshot.get("rsi14"), 50.0)
    if ret5 > 0.02 or c_ema20 > 0.01 or rsi > 55.0:
        reasons.append("strong momentum")
    elif c_ema20 > 0.0:
        reasons.append("trading above 20 EMA")

    # 2. Volume
    vol20 = _safe_float(snapshot.get("volume_ratio_20d"), 1.0)
    vol5 = _safe_float(snapshot.get("volume_ratio_5d"), 1.0)
    if vol20 > 1.2 or vol5 > 1.2:
        reasons.append("volume expansion")
    elif vol20 > 1.0:
        reasons.append("above average volume")

    # 3. Sector / Relative strength
    rel_sec = _safe_float(snapshot.get("rel_strength_sector_20d"), 0.0)
    rel_ihsg = _safe_float(snapshot.get("rel_strength_ihsg_20d"), 0.0)
    if rel_sec > 0.01:
        reasons.append("sector outperforming")
    elif rel_ihsg > 0.01:
        reasons.append("outperforming IHSG")

    # 4. Market regime
    breadth = _safe_float(snapshot.get("market_breadth"), 0.5)
    ihsg_ema = _safe_float(snapshot.get("ihsg_vs_ema20"), 0.0)
    if breadth >= 0.5 or ihsg_ema >= 0.0:
        reasons.append("market regime supportive")

    # 5. Volatility control
    atr_pct = _safe_float(snapshot.get("atr_pct"), 0.03)
    if atr_pct <= 0.035:
        reasons.append("controlled volatility")

    # Minimum fallback guarantees
    if len(reasons) < 2:
        if "strong momentum" not in reasons:
            reasons.append("favorable risk-reward")
        if "market regime supportive" not in reasons:
            reasons.append("supportive technical structure")

    return reasons[:4]


def _derive_market_summary(
    snapshot: dict[str, Any], market_summary: Optional[dict[str, str]]
) -> tuple[str, str, str]:
    if market_summary is not None:
        norm = {str(k).strip().lower(): str(v).strip() for k, v in market_summary.items()}
        ihsg = norm.get("ihsg", "Neutral")
        breadth = norm.get("breadth", "Neutral")
        vol = norm.get("volatility", "Normal")
        return ihsg, breadth, vol

    # Derive from snapshot if available
    ihsg_ema = _safe_float(snapshot.get("ihsg_vs_ema20"), 0.0)
    ihsg_ret = _safe_float(snapshot.get("ihsg_return_5d"), 0.0)
    if ihsg_ema > 0.005 or ihsg_ret > 0.01:
        ihsg = "Bullish"
    elif ihsg_ema < -0.005 or ihsg_ret < -0.01:
        ihsg = "Bearish"
    else:
        ihsg = "Neutral"

    mb_val = snapshot.get("market_breadth")
    if mb_val is not None:
        mb = _safe_float(mb_val, 0.5)
        if mb >= 0.55:
            breadth = "Positive"
        elif mb <= 0.45:
            breadth = "Negative"
        else:
            breadth = "Neutral"
    else:
        breadth = "Neutral"

    mv_val = snapshot.get("market_volatility")
    if mv_val is not None:
        mv = _safe_float(mv_val, 0.015)
        if mv > 0.02:
            vol = "Elevated"
        elif mv < 0.01:
            vol = "Low"
        else:
            vol = "Normal"
    else:
        vol = "Normal"

    return ihsg, breadth, vol


def format_dual_mode_signals(
    signals: Union[dict[str, Sequence[SignalRecord]], Sequence[SignalRecord]],
    target_date: Optional[date] = None,
    market_summary: Optional[dict[str, str]] = None,
) -> str:
    """Formats dual-mode signals in accordance with Guide 06 Section 11."""
    if isinstance(signals, dict):
        low_signals = list(signals.get("LOW_PRICE", []))
        high_signals = list(signals.get("HIGHER_PRICE", []))
        all_sigs = low_signals + high_signals
    else:
        all_sigs = list(signals)
        low_signals = [
            s for s in all_sigs
            if (s.mode or "").upper() == "LOW_PRICE"
            or (not s.mode and 50 <= s.entry_high <= 300)
        ]
        high_signals = [
            s for s in all_sigs
            if (s.mode or "").upper() == "HIGHER_PRICE"
            or (not s.mode and s.entry_high > 300)
        ]

    if target_date is None:
        if all_sigs:
            target_date = all_sigs[0].signal_date
        else:
            target_date = date.today()

    date_str = target_date.strftime("%d %b %Y")
    first_snapshot = all_sigs[0].feature_snapshot if all_sigs else {}
    ihsg_val, breadth_val, vol_val = _derive_market_summary(first_snapshot, market_summary)

    blocks: list[str] = [
        f"🤖 DAILY STOCK SIGNAL\n{date_str}",
        f"MARKET\nIHSG       : {ihsg_val}\nBreadth    : {breadth_val}\nVolatility : {vol_val}",
    ]

    def _format_mode_candidates(mode_sigs: list[SignalRecord]) -> str:
        if not mode_sigs:
            return "NO SIGNAL (No candidates passed hard gates)"

        cand_blocks = []
        for idx, s in enumerate(mode_sigs, 1):
            prob_val = int(round(s.predicted_probability * 100))
            ret_str = (
                _format_pct(s.expected_return * 100)
                if s.expected_return is not None
                else "N/A"
            )
            if s.entry_low < s.entry_high:
                entry_str = f"{s.entry_low:,.0f}–{s.entry_high:,.0f}"
            else:
                entry_str = f"{s.entry_low:,.0f}"

            tp_pct = ((s.tp_price / s.entry_high) - 1.0) * 100 if s.entry_high > 0 else 5.0
            sl_pct = ((s.sl_price / s.entry_low) - 1.0) * 100 if s.entry_low > 0 else -2.0
            tp_str = _format_pct(tp_pct)
            sl_str = _format_pct(sl_pct)

            bullets = derive_rationale(s.feature_snapshot)
            reasons_str = "\n   ".join(f"• {b}" for b in bullets)

            block = (
                f"{idx}. {s.ticker}\n"
                f"   Status: {s.signal}\n"
                f"   Probability: {prob_val}%\n"
                f"   Expected return: {ret_str}\n"
                f"   Entry / TP / SL: {entry_str} / {tp_str} / {sl_str}\n"
                f"   Horizon: {s.max_holding_days}D\n"
                f"   Model: {s.model_version}\n"
                f"   Reasons:\n"
                f"   {reasons_str}"
            )
            cand_blocks.append(block)

        return "\n\n".join(cand_blocks)

    low_text = _format_mode_candidates(low_signals)
    high_text = _format_mode_candidates(high_signals)
    blocks.append(f"━━━━━━━━━━━━━━━━\nMODE A — LOW_PRICE (IDR 50–300)\n{low_text}")
    blocks.append(f"━━━━━━━━━━━━━━━━\nMODE B — HIGHER_PRICE (> IDR 300)\n{high_text}")

    return "\n\n".join(blocks)


def format_daily_signals(
    signals: Union[Sequence[SignalRecord], dict[str, Sequence[SignalRecord]]],
    target_date: Optional[date] = None,
    market_summary: Optional[dict[str, str]] = None,
    dual_mode: bool = False,
) -> str:
    """Formats ranked daily signals into section Markdown format.

    If dual_mode is True or signals is a dict, formats according to Guide 06 dual-mode spec.
    Otherwise formats according to classic Section 42 single-mode spec for backward compatibility.
    """
    if dual_mode or isinstance(signals, dict):
        return format_dual_mode_signals(
            signals=signals,
            target_date=target_date,
            market_summary=market_summary,
        )

    sig_list = list(signals)
    if target_date is None:
        if sig_list:
            target_date = sig_list[0].signal_date
        else:
            target_date = date.today()

    date_str = target_date.strftime("%d %b %Y")
    first_snapshot = sig_list[0].feature_snapshot if sig_list else {}
    ihsg_val, breadth_val, vol_val = _derive_market_summary(first_snapshot, market_summary)

    blocks: list[str] = [
        f"🤖 DAILY STOCK SIGNAL\n{date_str}",
        f"MARKET\nIHSG       : {ihsg_val}\nBreadth    : {breadth_val}\nVolatility : {vol_val}",
    ]

    if not sig_list:
        blocks.append("━━━━━━━━━━━━━━━━")
        blocks.append("No BUY signals qualified for today.")
        return "\n\n".join(blocks)

    rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}

    for idx, s in enumerate(sig_list, 1):
        badge = rank_icons.get(idx, f"{idx}.")
        score_val = int(round(s.score))
        prob_val = int(round(s.predicted_probability * 100))
        ret_str = _format_pct(s.expected_return * 100) if s.expected_return is not None else "N/A"

        if s.entry_low < s.entry_high:
            entry_str = f"{s.entry_low:,.0f}–{s.entry_high:,.0f}"
        else:
            entry_str = f"{s.entry_low:,.0f}"

        tp_pct = ((s.tp_price / s.entry_high) - 1.0) * 100 if s.entry_high > 0 else 5.0
        sl_pct = ((s.sl_price / s.entry_low) - 1.0) * 100 if s.entry_low > 0 else -2.0

        tp_str = _format_pct(tp_pct)
        sl_str = _format_pct(sl_pct)

        bullets = derive_rationale(s.feature_snapshot)
        bullets_str = "\n".join(f"• {b}" for b in bullets)

        candidate_block = (
            f"━━━━━━━━━━━━━━━━\n\n"
            f"{badge} {s.ticker}\n"
            f"Score           : {score_val}/100\n"
            f"P(TP before SL) : {prob_val}%\n"
            f"Expected Return : {ret_str}\n\n"
            f"Entry           : {entry_str}\n"
            f"TP              : {tp_str}\n"
            f"SL              : {sl_str}\n"
            f"Max Hold        : {s.max_holding_days}D\n\n"
            f"Why:\n"
            f"{bullets_str}"
        )
        blocks.append(candidate_block)

    return "\n\n".join(blocks)
