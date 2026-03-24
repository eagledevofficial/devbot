"""
Eagle Trader - Main Entry Point
AI-Powered Paper Trading Bot by Eagle Development Group

Usage:
    python main.py                  # Run with Discord bot (default)
    python main.py --cli            # Run CLI-only mode (no Discord)
    python main.py --scan           # Run a single scan and exit
    python main.py --analyze AAPL   # Analyze a single ticker and exit
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime

import schedule

from src.utils.config import Config
from src.data.market_data import MarketDataEngine
from src.analysis.technical import TechnicalAnalyzer
from src.ai.gemini_engine import GeminiEngine
from src.trading.paper_engine import PaperTradingEngine
from src.strategy.orchestrator import TradingOrchestrator


def setup_logging(verbose: bool = False):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("eagle-trader/data/eagle_trader.log", mode="a"),
        ],
    )
    # Quiet down noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)


def create_orchestrator() -> TradingOrchestrator:
    """Build the full trading pipeline."""
    data_engine = MarketDataEngine(Config.WATCHLIST)
    analyzer = TechnicalAnalyzer(
        rsi_period=Config.RSI_PERIOD,
        macd_fast=Config.MACD_FAST,
        macd_slow=Config.MACD_SLOW,
        macd_signal=Config.MACD_SIGNAL,
        bb_period=Config.BOLLINGER_PERIOD,
        bb_std=Config.BOLLINGER_STD,
    )
    ai_engine = GeminiEngine()
    trading_engine = PaperTradingEngine(
        starting_balance=Config.STARTING_BALANCE,
        max_position_pct=Config.MAX_POSITION_SIZE,
        max_positions=Config.MAX_POSITIONS,
    )

    return TradingOrchestrator(
        data_engine=data_engine,
        analyzer=analyzer,
        ai_engine=ai_engine,
        trading_engine=trading_engine,
    )


def run_single_scan(orchestrator: TradingOrchestrator):
    """Run a single market scan and print results."""
    print("\n=== Eagle Trader — Single Scan ===\n")
    summary = orchestrator.run_scan()
    print(json.dumps(summary, indent=2))
    print(f"\n--- Portfolio ---")
    print(orchestrator.trading.get_portfolio_context_string())


def run_single_analyze(orchestrator: TradingOrchestrator, ticker: str):
    """Analyze a single ticker and print results."""
    ticker = ticker.upper()
    print(f"\n=== Eagle Trader — Analyzing {ticker} ===\n")

    result = orchestrator.force_analyze(ticker)
    if result is None:
        print(f"Could not analyze {ticker}. Is it a valid ticker?")
        return

    print("Technical Analysis:")
    print(json.dumps(result["technical"], indent=2))
    print()

    if result["ai_signal"]:
        print("AI Recommendation:")
        print(json.dumps(result["ai_signal"], indent=2))
    else:
        print("AI: No signal generated")


def run_cli_mode(orchestrator: TradingOrchestrator):
    """Run in CLI mode with scheduled scans (no Discord)."""
    print("""
    ╔══════════════════════════════════════════════════╗
    ║          EAGLE TRADER — CLI Mode                 ║
    ║      AI-Powered Paper Trading Engine             ║
    ║      Eagle Development Group                     ║
    ╚══════════════════════════════════════════════════╝
    """)

    portfolio = orchestrator.trading.get_portfolio_summary()
    print(f"  Portfolio:  ${portfolio['portfolio_value']:,.2f}")
    print(f"  Watchlist:  {', '.join(Config.WATCHLIST)}")
    print(f"  Scan Every: {Config.ANALYSIS_INTERVAL_MINUTES} minutes")
    print(f"  Market Hours: {Config.MARKET_OPEN} - {Config.MARKET_CLOSE} EST")
    print()

    def scheduled_scan():
        now = datetime.now()
        # Check market hours
        open_h, open_m = map(int, Config.MARKET_OPEN.split(":"))
        close_h, close_m = map(int, Config.MARKET_CLOSE.split(":"))
        current_minutes = now.hour * 60 + now.minute
        market_open = open_h * 60 + open_m
        market_close = close_h * 60 + close_m

        if now.weekday() >= 5:
            return
        if current_minutes < market_open or current_minutes > market_close:
            return

        run_single_scan(orchestrator)

    # Schedule scans
    schedule.every(Config.ANALYSIS_INTERVAL_MINUTES).minutes.do(scheduled_scan)

    # Run initial scan
    print("Running initial scan...\n")
    run_single_scan(orchestrator)

    print(f"\nScheduled scans every {Config.ANALYSIS_INTERVAL_MINUTES} min. Press Ctrl+C to stop.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEagle Trader stopped.")


def run_discord_mode(orchestrator: TradingOrchestrator):
    """Run with Discord bot integration."""
    from src.discord_bot.bot import create_bot

    if not Config.DISCORD_BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set in .env")
        print("Use --cli mode instead, or set the token.")
        sys.exit(1)

    print("""
    ╔══════════════════════════════════════════════════╗
    ║         EAGLE TRADER — Discord Mode              ║
    ║      AI-Powered Paper Trading Engine             ║
    ║      Eagle Development Group                     ║
    ╚══════════════════════════════════════════════════╝
    """)

    bot = create_bot(orchestrator)
    bot.run(Config.DISCORD_BOT_TOKEN, log_handler=None)


def main():
    parser = argparse.ArgumentParser(
        description="Eagle Trader - AI-Powered Paper Trading Bot"
    )
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode (no Discord)")
    parser.add_argument("--scan", action="store_true", help="Run a single scan and exit")
    parser.add_argument("--analyze", type=str, metavar="TICKER", help="Analyze a single ticker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Ensure data directory exists
    import os
    os.makedirs("eagle-trader/data", exist_ok=True)

    setup_logging(args.verbose)
    logger = logging.getLogger("eagle.main")

    # Validate config
    issues = Config.validate()
    for issue in issues:
        logger.warning(f"Config: {issue}")

    if not Config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is required. Set it in eagle-trader/.env")
        sys.exit(1)

    orchestrator = create_orchestrator()

    if args.scan:
        run_single_scan(orchestrator)
    elif args.analyze:
        run_single_analyze(orchestrator, args.analyze)
    elif args.cli:
        run_cli_mode(orchestrator)
    else:
        run_discord_mode(orchestrator)


if __name__ == "__main__":
    main()
