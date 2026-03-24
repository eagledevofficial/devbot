"""
Eagle Trader - Technical Analysis Module
Computes quantitative indicators used by the AI engine for trade signals.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger("eagle.analysis")


@dataclass
class TechnicalSignals:
    """Container for all computed technical indicators on a single ticker."""

    ticker: str

    # Price context
    current_price: float
    sma_20: float
    sma_50: float
    ema_12: float
    ema_26: float

    # Momentum
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    stoch_k: float
    stoch_d: float

    # Volatility
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width: float
    atr: float

    # Volume
    vwap: float
    volume_sma: float
    relative_volume: float

    # Trend
    adx: float
    plus_di: float
    minus_di: float

    def summary(self) -> dict:
        """Return a dict summary suitable for AI prompt injection."""
        return {
            "ticker": self.ticker,
            "price": self.current_price,
            "rsi": round(self.rsi, 2),
            "macd": round(self.macd, 4),
            "macd_signal": round(self.macd_signal, 4),
            "macd_histogram": round(self.macd_histogram, 4),
            "bb_position": self._bb_position(),
            "bb_width": round(self.bb_width, 4),
            "atr": round(self.atr, 2),
            "adx": round(self.adx, 2),
            "trend_direction": self._trend_direction(),
            "stoch_k": round(self.stoch_k, 2),
            "stoch_d": round(self.stoch_d, 2),
            "relative_volume": round(self.relative_volume, 2),
            "vwap_vs_price": round(self.current_price - self.vwap, 2),
            "sma_20": round(self.sma_20, 2),
            "sma_50": round(self.sma_50, 2),
            "momentum_score": self._momentum_score(),
            "signal_flags": self._signal_flags(),
        }

    def _bb_position(self) -> str:
        """Where price sits relative to Bollinger Bands."""
        if self.current_price >= self.bb_upper:
            return "ABOVE_UPPER"
        elif self.current_price <= self.bb_lower:
            return "BELOW_LOWER"
        elif self.current_price > self.bb_middle:
            return "UPPER_HALF"
        else:
            return "LOWER_HALF"

    def _trend_direction(self) -> str:
        """Determine overall trend from moving averages and ADX."""
        if self.adx < 20:
            return "RANGING"
        if self.plus_di > self.minus_di and self.ema_12 > self.ema_26:
            return "BULLISH"
        elif self.minus_di > self.plus_di and self.ema_12 < self.ema_26:
            return "BEARISH"
        return "MIXED"

    def _momentum_score(self) -> int:
        """
        Composite momentum score from -5 (strong bearish) to +5 (strong bullish).
        Each indicator contributes +1 or -1.
        """
        score = 0
        # RSI
        if self.rsi > 60:
            score += 1
        elif self.rsi < 40:
            score -= 1
        # MACD
        if self.macd > self.macd_signal:
            score += 1
        else:
            score -= 1
        # Bollinger position
        if self.current_price > self.bb_middle:
            score += 1
        else:
            score -= 1
        # Price vs VWAP
        if self.current_price > self.vwap:
            score += 1
        else:
            score -= 1
        # Trend (ADX + DI)
        if self.adx > 20 and self.plus_di > self.minus_di:
            score += 1
        elif self.adx > 20 and self.minus_di > self.plus_di:
            score -= 1
        return score

    def _signal_flags(self) -> list[str]:
        """Generate human-readable signal flags for the AI."""
        flags = []
        if self.rsi > 70:
            flags.append("RSI_OVERBOUGHT")
        elif self.rsi < 30:
            flags.append("RSI_OVERSOLD")
        if self.macd > self.macd_signal and self.macd_histogram > 0:
            flags.append("MACD_BULLISH_CROSS")
        elif self.macd < self.macd_signal and self.macd_histogram < 0:
            flags.append("MACD_BEARISH_CROSS")
        if self.current_price >= self.bb_upper:
            flags.append("BB_UPPER_TOUCH")
        elif self.current_price <= self.bb_lower:
            flags.append("BB_LOWER_TOUCH")
        if self.relative_volume > 2.0:
            flags.append("HIGH_VOLUME")
        elif self.relative_volume < 0.5:
            flags.append("LOW_VOLUME")
        if self.adx > 25:
            flags.append("STRONG_TREND")
        if self.current_price > self.sma_50:
            flags.append("ABOVE_SMA50")
        else:
            flags.append("BELOW_SMA50")
        if self.stoch_k > 80 and self.stoch_d > 80:
            flags.append("STOCH_OVERBOUGHT")
        elif self.stoch_k < 20 and self.stoch_d < 20:
            flags.append("STOCH_OVERSOLD")
        return flags


class TechnicalAnalyzer:
    """Computes technical indicators from OHLCV DataFrames."""

    def __init__(
        self,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std: int = 2,
    ):
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std = bb_std

    def analyze(self, ticker: str, df: pd.DataFrame) -> Optional[TechnicalSignals]:
        """
        Run full technical analysis on an OHLCV DataFrame.

        Args:
            ticker: Stock symbol
            df: DataFrame with Open, High, Low, Close, Volume columns

        Returns:
            TechnicalSignals dataclass or None if insufficient data
        """
        if df is None or len(df) < 50:
            logger.warning(f"{ticker}: insufficient data ({len(df) if df is not None else 0} bars)")
            return None

        try:
            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            volume = df["Volume"].astype(float)

            # Moving Averages
            sma_20 = ta.trend.sma_indicator(close, window=20).iloc[-1]
            sma_50 = ta.trend.sma_indicator(close, window=50).iloc[-1]
            ema_12 = ta.trend.ema_indicator(close, window=12).iloc[-1]
            ema_26 = ta.trend.ema_indicator(close, window=26).iloc[-1]

            # RSI
            rsi = ta.momentum.rsi(close, window=self.rsi_period).iloc[-1]

            # MACD
            macd_line = ta.trend.macd(close, window_slow=self.macd_slow, window_fast=self.macd_fast)
            macd_sig = ta.trend.macd_signal(
                close,
                window_slow=self.macd_slow,
                window_fast=self.macd_fast,
                window_sign=self.macd_signal,
            )
            macd_hist = ta.trend.macd_diff(
                close,
                window_slow=self.macd_slow,
                window_fast=self.macd_fast,
                window_sign=self.macd_signal,
            )

            # Stochastic
            stoch_k = ta.momentum.stoch(high, low, close, window=14, smooth_window=3).iloc[-1]
            stoch_d = ta.momentum.stoch_signal(high, low, close, window=14, smooth_window=3).iloc[-1]

            # Bollinger Bands
            bb = ta.volatility.BollingerBands(
                close, window=self.bb_period, window_dev=self.bb_std
            )
            bb_upper = bb.bollinger_hband().iloc[-1]
            bb_middle = bb.bollinger_mavg().iloc[-1]
            bb_lower = bb.bollinger_lband().iloc[-1]
            bb_width = bb.bollinger_wband().iloc[-1]

            # ATR
            atr = ta.volatility.average_true_range(high, low, close, window=14).iloc[-1]

            # ADX + Directional Indicators
            adx = ta.trend.adx(high, low, close, window=14).iloc[-1]
            plus_di = ta.trend.adx_pos(high, low, close, window=14).iloc[-1]
            minus_di = ta.trend.adx_neg(high, low, close, window=14).iloc[-1]

            # VWAP approximation (cumulative typical_price * volume / cumulative volume)
            typical_price = (high + low + close) / 3
            vwap = (typical_price * volume).sum() / volume.sum()

            # Volume analysis
            volume_sma = volume.rolling(window=20).mean().iloc[-1]
            current_volume = volume.iloc[-1]
            relative_volume = current_volume / volume_sma if volume_sma > 0 else 1.0

            return TechnicalSignals(
                ticker=ticker,
                current_price=round(close.iloc[-1], 2),
                sma_20=sma_20,
                sma_50=sma_50,
                ema_12=ema_12,
                ema_26=ema_26,
                rsi=rsi,
                macd=macd_line.iloc[-1],
                macd_signal=macd_sig.iloc[-1],
                macd_histogram=macd_hist.iloc[-1],
                stoch_k=stoch_k,
                stoch_d=stoch_d,
                bb_upper=bb_upper,
                bb_middle=bb_middle,
                bb_lower=bb_lower,
                bb_width=bb_width,
                atr=atr,
                vwap=round(vwap, 2),
                volume_sma=volume_sma,
                relative_volume=relative_volume,
                adx=adx,
                plus_di=plus_di,
                minus_di=minus_di,
            )

        except Exception as e:
            logger.error(f"Technical analysis failed for {ticker}: {e}")
            return None
