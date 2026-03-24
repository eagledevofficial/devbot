"""
Eagle Trader - Configuration Module
Loads settings from .env and provides defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


class Config:
    """Central configuration for Eagle Trader."""

    # API Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")

    # Discord Channels
    DISCORD_TRADING_CHANNEL_ID: str = os.getenv("DISCORD_TRADING_CHANNEL_ID", "")
    DISCORD_ALERTS_CHANNEL_ID: str = os.getenv("DISCORD_ALERTS_CHANNEL_ID", "")

    # Paper Trading
    STARTING_BALANCE: float = float(os.getenv("STARTING_BALANCE", "100000.00"))
    MAX_POSITION_SIZE: float = float(os.getenv("MAX_POSITION_SIZE", "0.10"))
    MAX_POSITIONS: int = int(os.getenv("MAX_POSITIONS", "10"))

    # Market Hours (EST)
    MARKET_OPEN: str = os.getenv("MARKET_OPEN", "09:30")
    MARKET_CLOSE: str = os.getenv("MARKET_CLOSE", "16:00")

    # Watchlist
    WATCHLIST: list[str] = [
        t.strip()
        for t in os.getenv(
            "WATCHLIST", "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD,SPY,QQQ"
        ).split(",")
    ]

    # Analysis Settings
    ANALYSIS_INTERVAL_MINUTES: int = 15
    RSI_PERIOD: int = 14
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9
    BOLLINGER_PERIOD: int = 20
    BOLLINGER_STD: int = 2

    # Risk Management
    STOP_LOSS_PCT: float = 0.03       # 3% stop loss
    TAKE_PROFIT_PCT: float = 0.06     # 6% take profit (2:1 reward/risk)
    MAX_DAILY_LOSS: float = 0.05      # 5% max daily portfolio loss

    # Gemini Model
    GEMINI_MODEL: str = "gemini-2.5-flash-preview-05-20"

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of missing required config values."""
        issues = []
        if not cls.GEMINI_API_KEY:
            issues.append("GEMINI_API_KEY is not set")
        if not cls.DISCORD_BOT_TOKEN:
            issues.append("DISCORD_BOT_TOKEN is not set (Discord features disabled)")
        return issues
