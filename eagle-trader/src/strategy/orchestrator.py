"""
Eagle Trader - Strategy Orchestrator
Wires data → analysis → AI → execution into a unified trading loop.
"""

import logging
from datetime import datetime
from typing import Optional, Callable

from src.data.market_data import MarketDataEngine
from src.analysis.technical import TechnicalAnalyzer, TechnicalSignals
from src.ai.gemini_engine import GeminiEngine, TradeSignal
from src.trading.paper_engine import PaperTradingEngine
from src.utils.config import Config

logger = logging.getLogger("eagle.strategy")


class TradingOrchestrator:
    """
    Central coordinator that runs the full trading pipeline:
    1. Fetch market data for watchlist
    2. Run technical analysis
    3. Send signals to Gemini AI
    4. Execute trades on paper engine
    5. Report results via callback (Discord, CLI, etc.)
    """

    def __init__(
        self,
        data_engine: Optional[MarketDataEngine] = None,
        analyzer: Optional[TechnicalAnalyzer] = None,
        ai_engine: Optional[GeminiEngine] = None,
        trading_engine: Optional[PaperTradingEngine] = None,
        on_trade: Optional[Callable] = None,
        on_alert: Optional[Callable] = None,
    ):
        self.data = data_engine or MarketDataEngine(Config.WATCHLIST)
        self.analyzer = analyzer or TechnicalAnalyzer(
            rsi_period=Config.RSI_PERIOD,
            macd_fast=Config.MACD_FAST,
            macd_slow=Config.MACD_SLOW,
            macd_signal=Config.MACD_SIGNAL,
            bb_period=Config.BOLLINGER_PERIOD,
            bb_std=Config.BOLLINGER_STD,
        )
        self.ai = ai_engine or GeminiEngine()
        self.trading = trading_engine or PaperTradingEngine(
            starting_balance=Config.STARTING_BALANCE,
            max_position_pct=Config.MAX_POSITION_SIZE,
            max_positions=Config.MAX_POSITIONS,
        )

        # Callbacks for external reporting (Discord bot hooks into these)
        self.on_trade = on_trade     # Called when a trade executes
        self.on_alert = on_alert     # Called for important alerts

        self._scan_count = 0

    def run_scan(self) -> dict:
        """
        Run a complete market scan cycle.

        Returns:
            Summary dict with scan results
        """
        self._scan_count += 1
        start_time = datetime.now()
        logger.info(f"=== Scan #{self._scan_count} started at {start_time.strftime('%H:%M:%S')} ===")

        # Step 1: Update existing position prices
        quotes = self.data.get_batch_quotes()
        triggered = self.trading.update_prices(quotes)

        for order in triggered:
            logger.info(f"Auto-triggered: {order.side.value} {order.ticker} — {order.reasoning}")
            if self.on_trade:
                self.on_trade(order, self.trading.get_portfolio_summary())

        # Step 2: Check daily loss limit
        if self.trading.daily_pnl_pct <= -(Config.MAX_DAILY_LOSS * 100):
            msg = (
                f"Daily loss limit hit ({self.trading.daily_pnl_pct:.1f}%). "
                f"Halting new trades for today."
            )
            logger.warning(msg)
            if self.on_alert:
                self.on_alert(msg)
            return {"status": "halted", "reason": "daily_loss_limit", "triggered": len(triggered)}

        # Step 3: Technical analysis on all watchlist tickers
        signals_list: list[TechnicalSignals] = []
        for ticker in self.data.watchlist:
            df = self.data.get_analysis_data(ticker)
            if df is not None:
                signals = self.analyzer.analyze(ticker, df)
                if signals:
                    signals_list.append(signals)

        logger.info(f"Analyzed {len(signals_list)}/{len(self.data.watchlist)} tickers")

        # Step 4: AI analysis
        portfolio_context = self.trading.get_portfolio_context_string()
        trade_signals = self.ai.analyze_batch(signals_list, portfolio_context)

        # Step 5: Execute actionable signals
        executed = []
        for signal in trade_signals:
            order = self._execute_signal(signal)
            if order and order.status.value == "FILLED":
                executed.append(order)
                if self.on_trade:
                    self.on_trade(order, self.trading.get_portfolio_summary())

        elapsed = (datetime.now() - start_time).total_seconds()
        summary = {
            "status": "completed",
            "scan_number": self._scan_count,
            "tickers_analyzed": len(signals_list),
            "ai_signals": len(trade_signals),
            "trades_executed": len(executed),
            "auto_triggered": len(triggered),
            "portfolio_value": self.trading.portfolio_value,
            "daily_pnl": self.trading.daily_pnl_value,
            "elapsed_seconds": round(elapsed, 1),
        }

        logger.info(
            f"Scan #{self._scan_count} complete: "
            f"{len(trade_signals)} signals, {len(executed)} trades, "
            f"${self.trading.portfolio_value:,.2f} portfolio | {elapsed:.1f}s"
        )

        return summary

    def _execute_signal(self, signal: TradeSignal):
        """Execute a single AI trade signal through the paper engine."""

        # Only act on BUY/SELL with sufficient confidence
        if signal.action == "HOLD" or signal.confidence < 0.6:
            logger.debug(
                f"Skipping {signal.ticker}: {signal.action} "
                f"(confidence: {signal.confidence:.0%})"
            )
            return None

        quote = self.data.get_quote(signal.ticker)
        if not quote:
            return None

        current_price = quote["price"]

        if signal.action == "BUY":
            # Don't buy if we already hold this ticker
            if signal.ticker in self.trading.positions:
                logger.debug(f"Already holding {signal.ticker}, skipping BUY")
                return None

            return self.trading.buy(
                ticker=signal.ticker,
                current_price=current_price,
                position_size_pct=signal.position_size_pct,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                reasoning=signal.reasoning,
            )

        elif signal.action == "SELL":
            if signal.ticker not in self.trading.positions:
                logger.debug(f"No position in {signal.ticker}, skipping SELL")
                return None

            return self.trading.sell(
                ticker=signal.ticker,
                current_price=current_price,
                reasoning=signal.reasoning,
            )

        return None

    def get_status(self) -> dict:
        """Get current system status for display."""
        portfolio = self.trading.get_portfolio_summary()
        return {
            "scans_completed": self._scan_count,
            "watchlist": self.data.watchlist,
            "portfolio": portfolio,
        }

    def force_analyze(self, ticker: str) -> Optional[dict]:
        """
        Force an immediate analysis of a single ticker.
        Useful for on-demand Discord commands.
        """
        df = self.data.get_analysis_data(ticker)
        if df is None:
            return None

        signals = self.analyzer.analyze(ticker, df)
        if signals is None:
            return None

        portfolio_context = self.trading.get_portfolio_context_string()
        trade_signal = self.ai.analyze(signals, portfolio_context)

        result = {
            "technical": signals.summary(),
            "ai_signal": None,
        }

        if trade_signal:
            result["ai_signal"] = {
                "action": trade_signal.action,
                "confidence": trade_signal.confidence,
                "entry_price": trade_signal.entry_price,
                "stop_loss": trade_signal.stop_loss,
                "take_profit": trade_signal.take_profit,
                "reasoning": trade_signal.reasoning,
                "risk_reward": trade_signal.risk_reward_ratio,
                "time_horizon": trade_signal.time_horizon,
            }

        return result
