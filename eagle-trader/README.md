# Eagle Trader

**AI-Powered Paper Trading Bot** by Eagle Development Group

An autonomous day trading system that combines quantitative technical analysis with Google Gemini 2.5 Flash AI to generate and execute trade signals in a simulated environment.

## Features

- **Real-time market data** via Yahoo Finance (free, no API key needed)
- **12+ technical indicators**: RSI, MACD, Bollinger Bands, ADX, Stochastic, ATR, VWAP, SMA/EMA, and more
- **Gemini 2.5 Flash AI** analyzes indicator confluence and generates trade signals with confidence scores
- **Paper trading engine** with full portfolio management, P&L tracking, stop loss/take profit
- **Risk management**: position sizing limits, daily loss limits, 2:1 reward/risk targeting
- **Discord integration** with live trade alerts and interactive commands
- **Persistent state**: portfolio survives restarts via JSON serialization

## Quick Start

### 1. Install dependencies

```bash
cd eagle-trader
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your Gemini API key and Discord token
```

### 3. Run

```bash
# Discord bot mode (default)
python main.py

# CLI mode (no Discord needed)
python main.py --cli

# Single scan
python main.py --scan

# Analyze one ticker
python main.py --analyze AAPL
```

## Discord Commands

| Command | Description |
|---------|-------------|
| `!portfolio` | Show current portfolio, positions, and P&L |
| `!analyze AAPL` | Run full technical + AI analysis on a ticker |
| `!scan` | Force an immediate market scan |
| `!watchlist` | Show watchlist with live prices |
| `!trades` | Show recent trade history |
| `!status` | Show bot system status |

## Architecture

```
Data (Yahoo Finance)
  → Technical Analysis (RSI, MACD, BB, ADX, VWAP...)
    → Gemini AI (trade signal generation)
      → Paper Trading Engine (simulated execution)
        → Discord Bot (alerts & commands)
```

## Configuration

Key settings in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | (required) | Google Gemini API key |
| `DISCORD_BOT_TOKEN` | (optional) | Discord bot token |
| `STARTING_BALANCE` | 100,000 | Paper trading starting cash |
| `MAX_POSITION_SIZE` | 0.10 | Max 10% of portfolio per position |
| `MAX_POSITIONS` | 10 | Max simultaneous positions |
| `WATCHLIST` | Top 10 | Comma-separated ticker symbols |

## Risk Controls

- **Stop Loss**: 3% per position (configurable)
- **Take Profit**: 6% per position (2:1 R/R)
- **Max Daily Loss**: 5% of portfolio — halts trading for the day
- **Position Sizing**: AI recommends size, capped at MAX_POSITION_SIZE
- **Confidence Gate**: Only trades with 60%+ AI confidence execute

## Paper Trading

This software runs in a **fully simulated environment**. No real money is at risk. The paper engine:

- Tracks positions, cash, and order history
- Fills at current market prices (simulating market orders)
- Monitors stop loss and take profit levels automatically
- Persists portfolio state to `data/portfolio.json`
- Records full trade history with entry/exit prices and P&L

## License

Internal project — Eagle Development Group
