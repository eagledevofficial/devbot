"""
Eagle Trader - Market Data Engine
Fetches real-time and historical market data via Yahoo Finance.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger("eagle.data")


class MarketDataEngine:
    """Fetches and caches market data for the trading pipeline."""

    def __init__(self, watchlist: list[str]):
        self.watchlist = [t.upper() for t in watchlist]
        self._cache: dict[str, pd.DataFrame] = {}
        self._quote_cache: dict[str, dict] = {}
        self._last_fetch: dict[str, datetime] = {}

    def get_historical(
        self,
        ticker: str,
        period: str = "3mo",
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data for a ticker.

        Args:
            ticker: Stock symbol (e.g. "AAPL")
            period: Lookback period ("1d", "5d", "1mo", "3mo", "6mo", "1y")
            interval: Bar interval ("1m", "5m", "15m", "1h", "1d")

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume
        """
        cache_key = f"{ticker}_{period}_{interval}"

        # Return cached data if less than 1 minute old
        if cache_key in self._cache and cache_key in self._last_fetch:
            age = datetime.now() - self._last_fetch[cache_key]
            if age < timedelta(minutes=1):
                return self._cache[cache_key]

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"No data returned for {ticker}")
                return None

            # Clean up columns — keep only OHLCV
            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.index.name = "Date"

            self._cache[cache_key] = df
            self._last_fetch[cache_key] = datetime.now()

            logger.info(f"Fetched {len(df)} bars for {ticker} ({period}/{interval})")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch data for {ticker}: {e}")
            return None

    def get_quote(self, ticker: str) -> Optional[dict]:
        """
        Get the current quote snapshot for a ticker.

        Returns dict with: price, change, change_pct, volume, market_cap, name
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.fast_info

            quote = {
                "ticker": ticker.upper(),
                "price": round(info.last_price, 2),
                "previous_close": round(info.previous_close, 2),
                "change": round(info.last_price - info.previous_close, 2),
                "change_pct": round(
                    ((info.last_price - info.previous_close) / info.previous_close)
                    * 100,
                    2,
                ),
                "volume": int(info.last_volume) if info.last_volume else 0,
                "market_cap": int(info.market_cap) if info.market_cap else 0,
                "timestamp": datetime.now().isoformat(),
            }

            self._quote_cache[ticker] = quote
            return quote

        except Exception as e:
            logger.error(f"Failed to get quote for {ticker}: {e}")
            return self._quote_cache.get(ticker)

    def get_batch_quotes(self) -> dict[str, dict]:
        """Fetch quotes for all watchlist tickers."""
        results = {}
        for ticker in self.watchlist:
            quote = self.get_quote(ticker)
            if quote:
                results[ticker] = quote
        return results

    def get_intraday(self, ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
        """Fetch today's intraday data."""
        return self.get_historical(ticker, period="1d", interval=interval)

    def get_analysis_data(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch the standard dataset used for technical analysis.
        3 months of daily data — enough for RSI(14), MACD(26), Bollinger(20).
        """
        return self.get_historical(ticker, period="3mo", interval="1d")
