"""
Eagle Trader - Gemini AI Analysis Engine
Uses Google Gemini 2.5 Flash to generate trade signals from technical data.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types

from src.analysis.technical import TechnicalSignals
from src.utils.config import Config

logger = logging.getLogger("eagle.ai")

SYSTEM_PROMPT = """You are Eagle Trader AI, an expert quantitative trading analyst.
You receive technical analysis data for stocks and produce actionable trade signals.

Your role:
1. Analyze the technical indicators provided (RSI, MACD, Bollinger Bands, ADX, VWAP, etc.)
2. Identify confluence — multiple indicators agreeing on direction
3. Assess risk/reward based on volatility (ATR, BB width) and trend strength (ADX)
4. Output a clear trade recommendation

RULES:
- Be conservative. Only recommend trades with strong confluence (3+ indicators agreeing).
- Always specify entry, stop loss, and take profit levels.
- Never recommend risking more than 3% of portfolio on a single trade.
- If signals are mixed or unclear, recommend HOLD/NO TRADE.
- Consider the momentum score and signal flags carefully.
- Factor in volume — high relative volume confirms moves, low volume suggests fakes.

You MUST respond with valid JSON in exactly this format:
{
    "ticker": "AAPL",
    "action": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 to 1.0,
    "entry_price": 150.00,
    "stop_loss": 145.50,
    "take_profit": 159.00,
    "position_size_pct": 0.05,
    "reasoning": "Brief 1-2 sentence explanation",
    "risk_reward_ratio": 2.0,
    "time_horizon": "intraday" | "swing" | "position"
}

If action is HOLD, set entry_price, stop_loss, take_profit to null and position_size_pct to 0.
"""


@dataclass
class TradeSignal:
    """AI-generated trade recommendation."""

    ticker: str
    action: str          # BUY, SELL, HOLD
    confidence: float    # 0.0 to 1.0
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size_pct: float
    reasoning: str
    risk_reward_ratio: Optional[float]
    time_horizon: str


class GeminiEngine:
    """Gemini 2.5 Flash-powered trade signal generator."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.model_name = Config.GEMINI_MODEL
        logger.info(f"Gemini engine initialized with model: {self.model_name}")

    def analyze(
        self,
        signals: TechnicalSignals,
        portfolio_context: str = "",
    ) -> Optional[TradeSignal]:
        """
        Send technical signals to Gemini and get a trade recommendation.

        Args:
            signals: Computed technical indicators for a ticker
            portfolio_context: Optional string describing current portfolio state

        Returns:
            TradeSignal or None if analysis fails
        """
        if not self.client:
            logger.error("Gemini API key not configured")
            return None

        prompt = self._build_prompt(signals, portfolio_context)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    top_p=0.8,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(response.text)

            trade_signal = TradeSignal(
                ticker=result["ticker"],
                action=result["action"].upper(),
                confidence=float(result["confidence"]),
                entry_price=result.get("entry_price"),
                stop_loss=result.get("stop_loss"),
                take_profit=result.get("take_profit"),
                position_size_pct=float(result.get("position_size_pct", 0)),
                reasoning=result.get("reasoning", ""),
                risk_reward_ratio=result.get("risk_reward_ratio"),
                time_horizon=result.get("time_horizon", "swing"),
            )

            logger.info(
                f"AI Signal: {trade_signal.ticker} → {trade_signal.action} "
                f"(confidence: {trade_signal.confidence:.0%})"
            )
            return trade_signal

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Gemini analysis failed for {signals.ticker}: {e}")
            return None

    def analyze_batch(
        self,
        signals_list: list[TechnicalSignals],
        portfolio_context: str = "",
    ) -> list[TradeSignal]:
        """Analyze multiple tickers and return all trade signals."""
        results = []
        for signals in signals_list:
            result = self.analyze(signals, portfolio_context)
            if result:
                results.append(result)
        return results

    def _build_prompt(
        self,
        signals: TechnicalSignals,
        portfolio_context: str,
    ) -> str:
        """Build the analysis prompt from technical signals."""
        summary = signals.summary()

        prompt = f"""Analyze the following technical data for {signals.ticker} and provide a trade recommendation.

## Technical Analysis Data
```json
{json.dumps(summary, indent=2)}
```

## Key Observations
- Price: ${signals.current_price}
- RSI({signals.rsi:.1f}): {"Overbought" if signals.rsi > 70 else "Oversold" if signals.rsi < 30 else "Neutral"}
- MACD Histogram: {"Positive (bullish)" if signals.macd_histogram > 0 else "Negative (bearish)"}
- Bollinger Position: {signals.summary()["bb_position"]}
- Trend: {signals.summary()["trend_direction"]} (ADX: {signals.adx:.1f})
- Relative Volume: {signals.relative_volume:.1f}x average
- Momentum Score: {signals.summary()["momentum_score"]} (range: -5 to +5)
- Signal Flags: {", ".join(signals.summary()["signal_flags"])}
"""

        if portfolio_context:
            prompt += f"\n## Current Portfolio Context\n{portfolio_context}\n"

        prompt += "\nProvide your trade recommendation as JSON."
        return prompt
