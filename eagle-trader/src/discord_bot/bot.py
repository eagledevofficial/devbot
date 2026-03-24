"""
Eagle Trader - Discord Bot Integration
Exposes trading commands and posts live alerts to your server.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands, tasks

from src.strategy.orchestrator import TradingOrchestrator
from src.trading.paper_engine import Order
from src.utils.config import Config

logger = logging.getLogger("eagle.discord")


class EagleTradingCog(commands.Cog):
    """Discord Cog for Eagle Trader commands and alerts."""

    def __init__(self, bot: commands.Bot, orchestrator: TradingOrchestrator):
        self.bot = bot
        self.orchestrator = orchestrator
        self.trading_channel: Optional[discord.TextChannel] = None
        self.alerts_channel: Optional[discord.TextChannel] = None

        # Wire orchestrator callbacks
        self.orchestrator.on_trade = self._on_trade_sync
        self.orchestrator.on_alert = self._on_alert_sync

        # Pending messages queue (since callbacks are sync but Discord is async)
        self._message_queue: list[tuple[str, discord.Embed]] = []

    async def cog_load(self):
        """Called when the cog is loaded."""
        self.auto_scan.start()
        self.process_queue.start()
        logger.info("EagleTradingCog loaded")

    async def cog_unload(self):
        self.auto_scan.cancel()
        self.process_queue.cancel()

    def _resolve_channels(self):
        """Find trading and alerts channels by ID or name."""
        if self.trading_channel and self.alerts_channel:
            return

        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if Config.DISCORD_TRADING_CHANNEL_ID and str(channel.id) == Config.DISCORD_TRADING_CHANNEL_ID:
                    self.trading_channel = channel
                elif "trading-dashboard" in channel.name or channel.name in ("eagle-trader", "trading", "paper-trading"):
                    if not self.trading_channel:
                        self.trading_channel = channel

                if Config.DISCORD_ALERTS_CHANNEL_ID and str(channel.id) == Config.DISCORD_ALERTS_CHANNEL_ID:
                    self.alerts_channel = channel
                elif "trading-alerts" in channel.name or channel.name in ("alerts", "ci-cd"):
                    if not self.alerts_channel:
                        self.alerts_channel = channel

        # Fallback: use trading channel for both
        if not self.alerts_channel:
            self.alerts_channel = self.trading_channel

    def _on_trade_sync(self, order: Order, portfolio_summary: dict):
        """Sync callback — queues a trade notification for async sending."""
        embed = self._build_trade_embed(order, portfolio_summary)
        self._message_queue.append(("trade", embed))

    def _on_alert_sync(self, message: str):
        """Sync callback — queues an alert for async sending."""
        embed = discord.Embed(
            title="Eagle Trader Alert",
            description=message,
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        self._message_queue.append(("alert", embed))

    @tasks.loop(seconds=2)
    async def process_queue(self):
        """Process queued messages from sync callbacks."""
        self._resolve_channels()
        while self._message_queue:
            msg_type, embed = self._message_queue.pop(0)
            channel = self.alerts_channel if msg_type == "alert" else self.trading_channel
            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Failed to send Discord message: {e}")

    @tasks.loop(minutes=Config.ANALYSIS_INTERVAL_MINUTES)
    async def auto_scan(self):
        """Automatic market scan every N minutes during market hours."""
        now = datetime.now()
        hour, minute = now.hour, now.minute
        current_time = hour * 60 + minute

        # Parse market hours
        open_h, open_m = map(int, Config.MARKET_OPEN.split(":"))
        close_h, close_m = map(int, Config.MARKET_CLOSE.split(":"))
        market_open = open_h * 60 + open_m
        market_close = close_h * 60 + close_m

        # Only scan during market hours (weekdays)
        if now.weekday() >= 5:  # Saturday/Sunday
            return
        if current_time < market_open or current_time > market_close:
            return

        logger.info("Auto-scan triggered")
        # Run scan in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, self.orchestrator.run_scan)

        # Post scan summary
        self._resolve_channels()
        if self.trading_channel and summary.get("trades_executed", 0) > 0:
            embed = self._build_scan_embed(summary)
            await self.trading_channel.send(embed=embed)

    @auto_scan.before_loop
    async def before_auto_scan(self):
        await self.bot.wait_until_ready()

    @process_queue.before_loop
    async def before_process_queue(self):
        await self.bot.wait_until_ready()

    # ── Commands ──────────────────────────────────────────────

    @commands.command(name="portfolio", aliases=["pf", "balance"])
    async def portfolio_cmd(self, ctx: commands.Context):
        """Show current portfolio status."""
        summary = self.orchestrator.trading.get_portfolio_summary()
        embed = self._build_portfolio_embed(summary)
        await ctx.send(embed=embed)

    @commands.command(name="analyze", aliases=["check"])
    async def analyze_cmd(self, ctx: commands.Context, ticker: str = ""):
        """Analyze a specific ticker. Usage: !analyze AAPL"""
        if not ticker:
            await ctx.send("Usage: `!analyze AAPL`")
            return

        ticker = ticker.upper()
        await ctx.send(f"Analyzing **{ticker}**... (this may take a moment)")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self.orchestrator.force_analyze, ticker
        )

        if result is None:
            await ctx.send(f"Could not analyze {ticker}. Check if it's a valid ticker.")
            return

        embed = self._build_analysis_embed(ticker, result)
        await ctx.send(embed=embed)

    @commands.command(name="scan")
    async def scan_cmd(self, ctx: commands.Context):
        """Force an immediate market scan."""
        await ctx.send("Running market scan...")

        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, self.orchestrator.run_scan)

        embed = self._build_scan_embed(summary)
        await ctx.send(embed=embed)

    @commands.command(name="watchlist", aliases=["wl"])
    async def watchlist_cmd(self, ctx: commands.Context):
        """Show current watchlist with live prices."""
        loop = asyncio.get_event_loop()
        quotes = await loop.run_in_executor(None, self.orchestrator.data.get_batch_quotes)

        embed = discord.Embed(
            title="Eagle Trader Watchlist",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        for ticker, quote in quotes.items():
            change_emoji = "+" if quote["change"] >= 0 else ""
            embed.add_field(
                name=ticker,
                value=(
                    f"${quote['price']:.2f}\n"
                    f"{change_emoji}{quote['change']:.2f} ({change_emoji}{quote['change_pct']:.1f}%)"
                ),
                inline=True,
            )

        await ctx.send(embed=embed)

    @commands.command(name="trades", aliases=["history"])
    async def trades_cmd(self, ctx: commands.Context, count: int = 5):
        """Show recent trade history. Usage: !trades [count]"""
        history = self.orchestrator.trading.trade_history
        if not history:
            await ctx.send("No trades yet.")
            return

        recent = history[-count:]
        embed = discord.Embed(
            title=f"Recent Trades (last {len(recent)})",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        for trade in reversed(recent):
            pnl_emoji = "+" if trade.pnl >= 0 else ""
            color_indicator = "profit" if trade.pnl >= 0 else "loss"
            embed.add_field(
                name=f"{trade.side} {trade.ticker}",
                value=(
                    f"{trade.quantity} shares\n"
                    f"Entry: ${trade.entry_price:.2f} -> Exit: ${trade.exit_price:.2f}\n"
                    f"P&L: {pnl_emoji}${trade.pnl:,.2f} ({pnl_emoji}{trade.pnl_pct:.1f}%) [{color_indicator}]\n"
                    f"_{trade.reasoning}_"
                ),
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.command(name="status")
    async def status_cmd(self, ctx: commands.Context):
        """Show bot system status."""
        status = self.orchestrator.get_status()
        embed = discord.Embed(
            title="Eagle Trader Status",
            color=discord.Color.green(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Scans Completed", value=str(status["scans_completed"]), inline=True)
        embed.add_field(name="Watchlist", value=", ".join(status["watchlist"]), inline=False)
        embed.add_field(
            name="Portfolio Value",
            value=f"${status['portfolio']['portfolio_value']:,.2f}",
            inline=True,
        )
        embed.add_field(
            name="Total P&L",
            value=f"${status['portfolio']['total_pnl']:,.2f} ({status['portfolio']['total_pnl_pct']:+.1f}%)",
            inline=True,
        )
        await ctx.send(embed=embed)

    # ── Embed Builders ────────────────────────────────────────

    def _build_trade_embed(self, order: Order, portfolio: dict) -> discord.Embed:
        color = discord.Color.green() if order.side.value == "BUY" else discord.Color.red()
        embed = discord.Embed(
            title=f"{'BUY' if order.side.value == 'BUY' else 'SELL'} {order.ticker}",
            color=color,
            timestamp=datetime.now(),
        )
        embed.add_field(name="Shares", value=str(order.quantity), inline=True)
        embed.add_field(name="Price", value=f"${order.fill_price:.2f}", inline=True)
        embed.add_field(
            name="Value",
            value=f"${order.quantity * order.fill_price:,.2f}",
            inline=True,
        )
        if order.stop_loss:
            embed.add_field(name="Stop Loss", value=f"${order.stop_loss:.2f}", inline=True)
        if order.take_profit:
            embed.add_field(name="Take Profit", value=f"${order.take_profit:.2f}", inline=True)
        if order.reasoning:
            embed.add_field(name="Reasoning", value=order.reasoning, inline=False)
        embed.set_footer(text=f"Portfolio: ${portfolio['portfolio_value']:,.2f}")
        return embed

    def _build_portfolio_embed(self, summary: dict) -> discord.Embed:
        pnl_color = discord.Color.green() if summary["total_pnl"] >= 0 else discord.Color.red()
        embed = discord.Embed(
            title="Eagle Trader Portfolio",
            color=pnl_color,
            timestamp=datetime.now(),
        )
        embed.add_field(name="Portfolio Value", value=f"${summary['portfolio_value']:,.2f}", inline=True)
        embed.add_field(name="Cash", value=f"${summary['cash']:,.2f}", inline=True)

        pnl_sign = "+" if summary["total_pnl"] >= 0 else ""
        embed.add_field(
            name="Total P&L",
            value=f"{pnl_sign}${summary['total_pnl']:,.2f} ({pnl_sign}{summary['total_pnl_pct']:.1f}%)",
            inline=True,
        )

        daily_sign = "+" if summary["daily_pnl"] >= 0 else ""
        embed.add_field(
            name="Today's P&L",
            value=f"{daily_sign}${summary['daily_pnl']:,.2f} ({daily_sign}{summary['daily_pnl_pct']:.1f}%)",
            inline=True,
        )
        embed.add_field(
            name="Win Rate",
            value=f"{summary['win_rate']}% ({summary['wins']}W/{summary['losses']}L)",
            inline=True,
        )
        embed.add_field(name="Positions", value=f"{summary['positions_count']}", inline=True)

        if summary["positions"]:
            pos_lines = []
            for p in summary["positions"]:
                sign = "+" if p["unrealized_pnl"] >= 0 else ""
                pos_lines.append(
                    f"**{p['ticker']}** — {p['quantity']} @ ${p['avg_cost']:.2f} "
                    f"(now ${p['current_price']:.2f}, {sign}${p['unrealized_pnl']:,.2f})"
                )
            embed.add_field(
                name="Open Positions",
                value="\n".join(pos_lines) or "None",
                inline=False,
            )

        return embed

    def _build_scan_embed(self, summary: dict) -> discord.Embed:
        embed = discord.Embed(
            title=f"Market Scan #{summary.get('scan_number', '?')}",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Tickers Analyzed", value=str(summary.get("tickers_analyzed", 0)), inline=True)
        embed.add_field(name="AI Signals", value=str(summary.get("ai_signals", 0)), inline=True)
        embed.add_field(name="Trades Executed", value=str(summary.get("trades_executed", 0)), inline=True)
        embed.add_field(
            name="Portfolio",
            value=f"${summary.get('portfolio_value', 0):,.2f}",
            inline=True,
        )
        embed.add_field(name="Duration", value=f"{summary.get('elapsed_seconds', 0)}s", inline=True)
        return embed

    def _build_analysis_embed(self, ticker: str, result: dict) -> discord.Embed:
        tech = result["technical"]
        ai = result.get("ai_signal")

        # Color based on momentum
        score = tech.get("momentum_score", 0)
        if score >= 2:
            color = discord.Color.green()
        elif score <= -2:
            color = discord.Color.red()
        else:
            color = discord.Color.gold()

        embed = discord.Embed(
            title=f"Analysis: {ticker}",
            color=color,
            timestamp=datetime.now(),
        )

        embed.add_field(name="Price", value=f"${tech['price']:.2f}", inline=True)
        embed.add_field(name="RSI", value=f"{tech['rsi']:.1f}", inline=True)
        embed.add_field(name="MACD", value=f"{tech['macd_histogram']:.4f}", inline=True)
        embed.add_field(name="Trend", value=tech["trend_direction"], inline=True)
        embed.add_field(name="BB Position", value=tech["bb_position"], inline=True)
        embed.add_field(name="Rel. Volume", value=f"{tech['relative_volume']:.1f}x", inline=True)
        embed.add_field(name="Momentum", value=f"{tech['momentum_score']}/5", inline=True)
        embed.add_field(name="ADX", value=f"{tech['adx']:.1f}", inline=True)

        flags = tech.get("signal_flags", [])
        if flags:
            embed.add_field(name="Signals", value=", ".join(flags), inline=False)

        if ai:
            action_emoji = {"BUY": "BUY", "SELL": "SELL", "HOLD": "HOLD"}.get(ai["action"], ai["action"])
            embed.add_field(
                name=f"AI Recommendation: {action_emoji}",
                value=(
                    f"Confidence: {ai['confidence']:.0%}\n"
                    f"Entry: ${ai['entry_price']}\n"
                    f"Stop Loss: ${ai['stop_loss']}\n"
                    f"Take Profit: ${ai['take_profit']}\n"
                    f"R/R: {ai['risk_reward']}:1 | {ai['time_horizon']}\n"
                    f"_{ai['reasoning']}_"
                ) if ai["action"] != "HOLD" else f"_{ai['reasoning']}_",
                inline=False,
            )

        return embed


def create_bot(orchestrator: TradingOrchestrator) -> commands.Bot:
    """Create and configure the Discord bot."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True

    bot = commands.Bot(
        command_prefix="!",
        intents=intents,
        description="Eagle Trader - AI-Powered Paper Trading Bot",
    )

    @bot.event
    async def on_ready():
        logger.info(f"Eagle Trader connected as {bot.user} in {len(bot.guilds)} guild(s)")
        await bot.add_cog(EagleTradingCog(bot, orchestrator))
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="the markets | !portfolio",
            )
        )

    return bot
