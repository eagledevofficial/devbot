"""
Eagle Trader - Paper Trading Engine
Simulated brokerage that tracks positions, orders, and P&L with real prices.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("eagle.trading")


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """A trade order."""

    id: str
    ticker: str
    side: OrderSide
    quantity: int
    price: float              # requested price
    fill_price: float = 0.0   # actual fill price
    status: OrderStatus = OrderStatus.PENDING
    timestamp: str = ""
    reasoning: str = ""
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class Position:
    """An open position in the portfolio."""

    ticker: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: str = ""

    def __post_init__(self):
        if not self.opened_at:
            self.opened_at = datetime.now().isoformat()

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100

    def should_stop_loss(self) -> bool:
        return self.stop_loss is not None and self.current_price <= self.stop_loss

    def should_take_profit(self) -> bool:
        return self.take_profit is not None and self.current_price >= self.take_profit


@dataclass
class TradeRecord:
    """A completed trade for the history log."""

    ticker: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    hold_duration: str
    entry_time: str
    exit_time: str
    reasoning: str = ""


class PaperTradingEngine:
    """
    Simulated trading engine with full portfolio management.

    Features:
    - Cash and position tracking
    - Order execution at market prices
    - Stop loss / take profit monitoring
    - Full trade history and P&L tracking
    - Portfolio state persistence to disk
    """

    def __init__(
        self,
        starting_balance: float = 100_000.0,
        max_position_pct: float = 0.10,
        max_positions: int = 10,
        save_path: Optional[str] = None,
    ):
        self.starting_balance = starting_balance
        self.cash = starting_balance
        self.max_position_pct = max_position_pct
        self.max_positions = max_positions

        self.positions: dict[str, Position] = {}
        self.orders: list[Order] = []
        self.trade_history: list[TradeRecord] = []
        self.daily_pnl: list[dict] = []

        self._order_counter = 0
        self._day_start_value = starting_balance

        self.save_path = Path(save_path) if save_path else Path("eagle-trader/data/portfolio.json")
        self.save_path.parent.mkdir(parents=True, exist_ok=True)

        # Try to load existing state
        self._load_state()

        logger.info(
            f"Paper engine initialized: ${self.cash:,.2f} cash, "
            f"{len(self.positions)} positions"
        )

    @property
    def portfolio_value(self) -> float:
        """Total portfolio value = cash + all position market values."""
        positions_value = sum(p.market_value for p in self.positions.values())
        return self.cash + positions_value

    @property
    def total_pnl(self) -> float:
        return self.portfolio_value - self.starting_balance

    @property
    def total_pnl_pct(self) -> float:
        return (self.total_pnl / self.starting_balance) * 100

    @property
    def daily_pnl_value(self) -> float:
        return self.portfolio_value - self._day_start_value

    @property
    def daily_pnl_pct(self) -> float:
        if self._day_start_value == 0:
            return 0.0
        return (self.daily_pnl_value / self._day_start_value) * 100

    def buy(
        self,
        ticker: str,
        current_price: float,
        position_size_pct: float = 0.05,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reasoning: str = "",
    ) -> Optional[Order]:
        """
        Execute a paper buy order.

        Args:
            ticker: Stock symbol
            current_price: Current market price for fill
            position_size_pct: Fraction of portfolio to allocate (0.0 to 1.0)
            stop_loss: Stop loss price
            take_profit: Take profit price
            reasoning: AI reasoning for the trade

        Returns:
            Filled Order or None if rejected
        """
        # Validate
        if len(self.positions) >= self.max_positions and ticker not in self.positions:
            logger.warning(f"Max positions ({self.max_positions}) reached, rejecting {ticker} BUY")
            return self._reject_order(ticker, OrderSide.BUY, current_price, "Max positions reached")

        # Clamp position size
        size_pct = min(position_size_pct, self.max_position_pct)
        allocation = self.portfolio_value * size_pct
        allocation = min(allocation, self.cash)  # Can't spend more than we have

        if allocation < current_price:
            logger.warning(f"Insufficient funds for {ticker} BUY")
            return self._reject_order(ticker, OrderSide.BUY, current_price, "Insufficient funds")

        quantity = int(allocation / current_price)
        if quantity == 0:
            return self._reject_order(ticker, OrderSide.BUY, current_price, "Order too small")

        cost = quantity * current_price
        self.cash -= cost

        # Update or create position
        if ticker in self.positions:
            pos = self.positions[ticker]
            total_qty = pos.quantity + quantity
            pos.avg_cost = ((pos.avg_cost * pos.quantity) + cost) / total_qty
            pos.quantity = total_qty
            pos.current_price = current_price
            if stop_loss:
                pos.stop_loss = stop_loss
            if take_profit:
                pos.take_profit = take_profit
        else:
            self.positions[ticker] = Position(
                ticker=ticker,
                quantity=quantity,
                avg_cost=current_price,
                current_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

        order = self._create_order(
            ticker, OrderSide.BUY, quantity, current_price,
            stop_loss=stop_loss, take_profit=take_profit, reasoning=reasoning,
        )
        order.fill_price = current_price
        order.status = OrderStatus.FILLED

        logger.info(
            f"BUY {quantity} {ticker} @ ${current_price:.2f} "
            f"(${cost:,.2f}) | Cash: ${self.cash:,.2f}"
        )

        self._save_state()
        return order

    def sell(
        self,
        ticker: str,
        current_price: float,
        quantity: Optional[int] = None,
        reasoning: str = "",
    ) -> Optional[Order]:
        """
        Execute a paper sell order. Sells entire position if quantity is None.

        Returns:
            Filled Order or None if rejected
        """
        if ticker not in self.positions:
            logger.warning(f"No position in {ticker} to sell")
            return self._reject_order(ticker, OrderSide.SELL, current_price, "No position")

        pos = self.positions[ticker]
        sell_qty = quantity or pos.quantity
        sell_qty = min(sell_qty, pos.quantity)

        proceeds = sell_qty * current_price
        self.cash += proceeds

        # Record trade
        pnl = (current_price - pos.avg_cost) * sell_qty
        pnl_pct = ((current_price - pos.avg_cost) / pos.avg_cost) * 100

        self.trade_history.append(TradeRecord(
            ticker=ticker,
            side="SELL",
            quantity=sell_qty,
            entry_price=pos.avg_cost,
            exit_price=current_price,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            hold_duration=str(datetime.now() - datetime.fromisoformat(pos.opened_at)),
            entry_time=pos.opened_at,
            exit_time=datetime.now().isoformat(),
            reasoning=reasoning,
        ))

        # Update or remove position
        if sell_qty >= pos.quantity:
            del self.positions[ticker]
        else:
            pos.quantity -= sell_qty

        order = self._create_order(
            ticker, OrderSide.SELL, sell_qty, current_price, reasoning=reasoning,
        )
        order.fill_price = current_price
        order.status = OrderStatus.FILLED

        pnl_emoji = "+" if pnl >= 0 else ""
        logger.info(
            f"SELL {sell_qty} {ticker} @ ${current_price:.2f} "
            f"(P&L: {pnl_emoji}${pnl:,.2f} / {pnl_emoji}{pnl_pct:.1f}%)"
        )

        self._save_state()
        return order

    def update_prices(self, quotes: dict[str, dict]) -> list[Order]:
        """
        Update position prices and check stop loss / take profit triggers.

        Args:
            quotes: Dict of ticker -> quote data (must have "price" key)

        Returns:
            List of auto-triggered orders (stop loss / take profit fills)
        """
        triggered_orders = []

        for ticker, pos in list(self.positions.items()):
            if ticker in quotes:
                pos.current_price = quotes[ticker]["price"]

                if pos.should_stop_loss():
                    logger.warning(f"STOP LOSS triggered for {ticker} @ ${pos.current_price:.2f}")
                    order = self.sell(
                        ticker, pos.current_price,
                        reasoning=f"Stop loss triggered (limit: ${pos.stop_loss:.2f})",
                    )
                    if order:
                        triggered_orders.append(order)

                elif pos.should_take_profit():
                    logger.info(f"TAKE PROFIT triggered for {ticker} @ ${pos.current_price:.2f}")
                    order = self.sell(
                        ticker, pos.current_price,
                        reasoning=f"Take profit triggered (target: ${pos.take_profit:.2f})",
                    )
                    if order:
                        triggered_orders.append(order)

        return triggered_orders

    def get_portfolio_summary(self) -> dict:
        """Get a complete portfolio summary for display or AI context."""
        positions_data = []
        for ticker, pos in self.positions.items():
            positions_data.append({
                "ticker": ticker,
                "quantity": pos.quantity,
                "avg_cost": round(pos.avg_cost, 2),
                "current_price": round(pos.current_price, 2),
                "market_value": round(pos.market_value, 2),
                "unrealized_pnl": round(pos.unrealized_pnl, 2),
                "unrealized_pnl_pct": round(pos.unrealized_pnl_pct, 2),
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
            })

        # Win/loss stats from trade history
        wins = [t for t in self.trade_history if t.pnl > 0]
        losses = [t for t in self.trade_history if t.pnl <= 0]
        total_trades = len(self.trade_history)

        return {
            "portfolio_value": round(self.portfolio_value, 2),
            "cash": round(self.cash, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct, 2),
            "daily_pnl": round(self.daily_pnl_value, 2),
            "daily_pnl_pct": round(self.daily_pnl_pct, 2),
            "positions_count": len(self.positions),
            "positions": positions_data,
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / total_trades * 100, 1) if total_trades > 0 else 0,
            "avg_win": round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0,
        }

    def get_portfolio_context_string(self) -> str:
        """Get portfolio state as a string for AI prompt context."""
        summary = self.get_portfolio_summary()
        lines = [
            f"Portfolio Value: ${summary['portfolio_value']:,.2f}",
            f"Cash Available: ${summary['cash']:,.2f}",
            f"Total P&L: ${summary['total_pnl']:,.2f} ({summary['total_pnl_pct']:+.1f}%)",
            f"Today's P&L: ${summary['daily_pnl']:,.2f} ({summary['daily_pnl_pct']:+.1f}%)",
            f"Open Positions: {summary['positions_count']}/{self.max_positions}",
            f"Trade Record: {summary['wins']}W / {summary['losses']}L ({summary['win_rate']}% win rate)",
        ]
        if summary["positions"]:
            lines.append("\nOpen Positions:")
            for p in summary["positions"]:
                lines.append(
                    f"  {p['ticker']}: {p['quantity']} shares @ ${p['avg_cost']:.2f} "
                    f"(now ${p['current_price']:.2f}, P&L: ${p['unrealized_pnl']:+,.2f})"
                )
        return "\n".join(lines)

    def reset_daily(self):
        """Reset daily tracking — call at market open."""
        self._day_start_value = self.portfolio_value
        logger.info(f"Daily reset. Starting value: ${self._day_start_value:,.2f}")

    def _create_order(self, ticker, side, quantity, price, **kwargs) -> Order:
        self._order_counter += 1
        order = Order(
            id=f"ET-{self._order_counter:06d}",
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            **kwargs,
        )
        self.orders.append(order)
        return order

    def _reject_order(self, ticker, side, price, reason) -> Order:
        order = self._create_order(ticker, side, 0, price, reasoning=reason)
        order.status = OrderStatus.REJECTED
        return order

    def _save_state(self):
        """Persist portfolio state to disk."""
        state = {
            "cash": self.cash,
            "starting_balance": self.starting_balance,
            "positions": {
                t: {
                    "ticker": p.ticker,
                    "quantity": p.quantity,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "opened_at": p.opened_at,
                }
                for t, p in self.positions.items()
            },
            "trade_history": [asdict(t) for t in self.trade_history[-100:]],  # Keep last 100
            "order_counter": self._order_counter,
            "saved_at": datetime.now().isoformat(),
        }
        try:
            self.save_path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.error(f"Failed to save portfolio state: {e}")

    def _load_state(self):
        """Load portfolio state from disk if it exists."""
        if not self.save_path.exists():
            return

        try:
            state = json.loads(self.save_path.read_text())
            self.cash = state["cash"]
            self.starting_balance = state.get("starting_balance", self.starting_balance)
            self._order_counter = state.get("order_counter", 0)

            for t, p in state.get("positions", {}).items():
                self.positions[t] = Position(**p)

            for t in state.get("trade_history", []):
                self.trade_history.append(TradeRecord(**t))

            logger.info(f"Loaded portfolio state from {self.save_path}")

        except Exception as e:
            logger.error(f"Failed to load portfolio state: {e}")
