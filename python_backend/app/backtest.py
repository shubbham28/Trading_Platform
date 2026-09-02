"""
Backtesting engine.

The contract this engine enforces, and the reasons for each rule:

FILLS HAPPEN ON THE NEXT BAR'S OPEN. A signal produced from bar i's close is
filled at bar i+1's open. You cannot observe a bar's closing price and also
trade at it; an engine that does reports profits that were never reachable.
This single rule is usually the difference between a backtest that looks
excellent and one that is honest.

THE ENGINE OWNS THE POSITION. Strategies are pure: they receive the position
and return an intent. Previously both sides kept their own copy, and when a
buy was silently declined for insufficient capital the strategy believed it was
long for the rest of the run and stopped trading. There is now one copy, so
there is nothing to desync.

COSTS ARE ON BY DEFAULT. Slippage defaults to 1bp rather than zero, because
zero-cost trading is not a conservative assumption, it is a false one. Every
result carries the cost assumptions that produced it.

NOTHING IS DROPPED SILENTLY. Orders that cannot fill (no next bar, not enough
capital, shorting while shorts are disabled) are counted and reported.
"""
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.session import build_contexts, parse_bar_minutes, audit_early_close_risk
from indicators import calculate_all_indicators
from strategies.base import BaseStrategy, Position, Signal, Trade

# Regular-session bars per day, used to annualise risk metrics. A minute-bar
# strategy has ~98,280 observations a year, not 252; annualising it with
# sqrt(252) overstates Sharpe by roughly twentyfold.
SESSION_MINUTES = 390
TRADING_DAYS_PER_YEAR = 252


def periods_per_year(timeframe: str) -> float:
    """Observations per year for a given bar size, for annualising Sharpe."""
    bar_minutes = parse_bar_minutes(timeframe)
    if bar_minutes is None:
        if timeframe.endswith('Week'):
            return 52.0
        if timeframe.endswith('Month'):
            return 12.0
        return float(TRADING_DAYS_PER_YEAR)
    return (SESSION_MINUTES / bar_minutes) * TRADING_DAYS_PER_YEAR


class BacktestConfig(BaseModel):
    """Backtest configuration."""
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 10000.0
    strategy_id: str
    parameters: Dict[str, Any] = {}

    timeframe: str = '1Day'

    # Commission as a fraction of notional (0.0005 = 5bp). Alpaca equities are
    # commission-free, so this is usually 0 and slippage is the real cost.
    commission: float = 0.0
    # Slippage in basis points, applied against the fill on both entry and exit.
    # Non-zero by default on purpose: see the module docstring.
    slippage_bps: float = 1.0

    # Percentage of equity committed to a single position. 100 reproduces the
    # all-in behaviour this engine used to hardcode. Real limits arrive with the
    # Risk Gate; this knob exists so the assumption is at least visible.
    max_position_pct: float = Field(default=100.0, gt=0, le=100)
    allow_short: bool = False


class EquityPoint(BaseModel):
    """Equity curve data point."""
    timestamp: Any
    equity: float
    drawdown: float


class ExecutionAudit(BaseModel):
    """What the engine could not do, and why.

    An empty audit is a meaningful result. A populated one usually means the
    reported performance is not the strategy's performance.
    """
    intents_unfilled_no_next_bar: int = 0
    intents_rejected_insufficient_capital: int = 0
    intents_rejected_shorts_disabled: int = 0
    forced_liquidations: int = 0
    bars_skipped_warmup: int = 0
    sessions_with_early_close_risk: List[str] = []


class BacktestResult(BaseModel):
    """Backtest results."""
    strategy_id: str
    symbol: str
    start_date: str
    end_date: str
    # The parameters the strategy actually ran with. Without them a stored run
    # is not reproducible: two runs of sma_crossover on different periods are
    # indistinguishable, and neither can be re-created from the record.
    parameters: Dict[str, Any] = {}
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    # None rather than a fake ratio when there are no losing trades. The old
    # code divided by 1.0, producing a number that read like a ratio.
    profit_factor: Optional[float]
    trades: List[Dict[str, Any]]
    equity_curve: List[Dict[str, Any]]

    # Every result states the assumptions that produced it, so a number can
    # never be quoted without its costs.
    timeframe: str
    commission: float
    slippage_bps: float
    max_position_pct: float
    allow_short: bool
    audit: ExecutionAudit

    # Persistence outcome. Reported rather than swallowed: a result that was not
    # stored looks identical to a stored one on screen, and the difference only
    # surfaces later when someone cannot find the run they remember running.
    run_id: Optional[int] = None
    persisted: bool = False
    persistence_error: Optional[str] = None


class BacktestEngine:
    """Backtesting engine for strategy evaluation."""

    def __init__(self, config: BacktestConfig, strategy: BaseStrategy):
        self.config = config
        self.strategy = strategy

        self.cash = config.initial_capital
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []
        self.audit = ExecutionAudit()

        # Commission accrued on the open leg, carried until the position closes
        # so a round trip's pnl is net of both legs.
        self._open_commission = 0.0

    # -- public ------------------------------------------------------------

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """Run the simulation over `df` and return results."""
        if df.empty:
            raise ValueError("No data provided for backtest")
        if 'timestamp' not in df.columns:
            raise ValueError("Backtest data must have a 'timestamp' column")

        df = df.reset_index(drop=True)
        # Indicators are computed once, over the whole frame, using only causal
        # operations. test_no_lookahead.py asserts that property per strategy.
        prepared = self.strategy.prepare(calculate_all_indicators(df))
        contexts = build_contexts(prepared, self.config.timeframe)

        self.audit.sessions_with_early_close_risk = [
            d.isoformat()
            for d in audit_early_close_risk(prepared, self.config.timeframe)
        ]

        warmup = self.strategy.warmup_bars()
        peak_equity = self.config.initial_capital
        pending: Optional[Signal] = None

        for i in range(len(prepared)):
            bar = prepared.iloc[i]

            # 1. Fill the previous bar's intent at this bar's open. Ordering
            #    matters: the fill precedes this bar's marking and decision, so
            #    no decision is ever made with knowledge of its own fill price
            #    before that fill was possible.
            if pending is not None:
                self._apply(pending, float(bar['open']), bar['timestamp'])
                pending = None

            # 2. Mark equity at this bar's close.
            equity = self._equity(float(bar['close']))
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
            self.equity_curve.append(EquityPoint(
                timestamp=bar['timestamp'], equity=equity, drawdown=drawdown
            ))

            # 3. Ask the strategy for the next intent, showing it only the bars
            #    up to and including this one.
            if i < warmup:
                self.audit.bars_skipped_warmup += 1
                continue

            signal = self.strategy.analyze(
                prepared.iloc[:i + 1], contexts[i], self.position
            )
            if signal.action in ('buy', 'sell'):
                if i + 1 < len(prepared):
                    pending = signal
                else:
                    # The final bar's intent has no bar to fill against. Counted
                    # rather than quietly filled at a price that never existed.
                    self.audit.intents_unfilled_no_next_bar += 1

        # Any position still open at the end is closed at the last close so the
        # equity figure is realised, and flagged so it is not mistaken for a
        # strategy exit.
        if self.position is not None:
            last = prepared.iloc[-1]
            self._close(
                float(last['close']), last['timestamp'],
                "End of backtest period", forced=True
            )
            self.audit.forced_liquidations += 1

        return self._generate_report()

    # -- execution ---------------------------------------------------------

    def _fill_price(self, reference: float, delta_qty: int) -> float:
        """Reference price adjusted for slippage in the direction being traded.

        Buying pays up, selling receives less. One rule covers entries and
        exits, longs and shorts, because it depends only on the sign of the
        quantity change.
        """
        edge = self.config.slippage_bps / 10_000.0
        return reference * (1 + edge) if delta_qty > 0 else reference * (1 - edge)

    def _commission_on(self, qty: int, price: float) -> float:
        return abs(qty) * price * self.config.commission

    def _target_qty(self, price: float, direction: int) -> int:
        """Signed share count for a new position at `price`.

        `direction` is +1 for long, -1 for short.

        The commission is reserved out of the budget rather than charged on top
        of it. Sizing against gross equity and then adding commission makes the
        order cost more than the account holds, so at 100% sizing every order
        with a non-zero commission is declined -- which is not a position-sizing
        policy, it is an off-by-a-fee bug that shows up as an empty trade list.
        """
        budget = self._equity(price) * (self.config.max_position_pct / 100.0)
        cost_per_share = price * (1 + self.config.commission)
        shares = int(budget // cost_per_share)
        return shares * direction

    def _apply(self, signal: Signal, reference_price: float, timestamp) -> None:
        """Interpret an intent against the current position and execute it."""
        action = signal.action

        if self.position is None:
            direction = 1 if action == 'buy' else -1
            if direction == -1 and not self.config.allow_short:
                self.audit.intents_rejected_shorts_disabled += 1
                return
            self._open(direction, reference_price, timestamp, signal.reason)
            return

        # Holding a position: an intent in the opposing direction closes it. An
        # intent in the same direction is a no-op rather than a pyramid, which
        # keeps position sizing a single decision made at entry.
        closing = (
            (self.position.is_long and action == 'sell')
            or (self.position.is_short and action == 'buy')
        )
        if closing:
            price = self._fill_price(reference_price, -self.position.qty)
            self._close(price, timestamp, signal.reason, forced=False)

    def _open(self, direction: int, reference_price: float, timestamp, reason: str) -> None:
        probe = self._fill_price(reference_price, direction)
        qty = self._target_qty(probe, direction)
        if qty == 0:
            self.audit.intents_rejected_insufficient_capital += 1
            return

        price = self._fill_price(reference_price, qty)
        commission = self._commission_on(qty, price)

        # Longs must be affordable. Shorts credit the account, so the binding
        # constraint is only the commission.
        cost = qty * price + commission
        if cost > self.cash:
            self.audit.intents_rejected_insufficient_capital += 1
            return

        self.cash -= cost
        self._open_commission = commission
        self.position = Position(qty=qty, entry_price=price, entry_time=timestamp)

    def _close(self, price: float, timestamp, reason: str, forced: bool) -> None:
        pos = self.position
        if pos is None:
            return

        commission = self._commission_on(pos.qty, price)
        # Closing moves the position to zero, so the cash change is +qty*price
        # for a long and -|qty|*price for a short. Signed qty makes it one line.
        self.cash += pos.qty * price - commission

        total_commission = self._open_commission + commission
        pnl = (price - pos.entry_price) * pos.qty - total_commission
        pnl_pct = pos.unrealized_pct(price)

        self.trades.append(Trade(
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=timestamp,
            exit_price=price,
            quantity=abs(pos.qty),
            side='long' if pos.is_long else 'short',
            pnl=pnl,
            pnl_pct=pnl_pct,
            commission=total_commission,
            reason=reason,
            forced_liquidation=forced,
        ))

        self.position = None
        self._open_commission = 0.0

    def _equity(self, mark_price: float) -> float:
        """Cash plus the marked value of any open position.

        Signed quantity means a short's negative market value is subtracted
        from the cash its sale raised, which is what makes shorts mark correctly
        without a separate branch.
        """
        held = self.position.qty * mark_price if self.position else 0.0
        return self.cash + held

    # -- reporting ---------------------------------------------------------

    def _generate_report(self) -> BacktestResult:
        final_equity = self.equity_curve[-1].equity if self.equity_curve else self.cash
        # The position is always flat by this point, so cash is the realised
        # figure. Prefer it over the last mark, which was taken before the
        # forced liquidation.
        if self.position is None:
            final_equity = self.cash

        total_return = final_equity - self.config.initial_capital
        total_return_pct = (total_return / self.config.initial_capital) * 100

        wins = [t.pnl for t in self.trades if t.pnl is not None and t.pnl > 0]
        losses = [abs(t.pnl) for t in self.trades if t.pnl is not None and t.pnl < 0]

        total_trades = len(self.trades)
        win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0

        gross_loss = sum(losses)
        # None, not a ratio against a made-up denominator, when nothing lost.
        profit_factor = (sum(wins) / gross_loss) if gross_loss > 0 else None

        sharpe, sortino = self._risk_ratios()
        max_drawdown = max((ep.drawdown for ep in self.equity_curve), default=0.0)

        return BacktestResult(
            strategy_id=self.config.strategy_id,
            symbol=self.config.symbol,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            parameters=self.config.parameters,
            initial_capital=self.config.initial_capital,
            final_capital=final_equity,
            total_return=total_return,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown * 100,
            total_trades=total_trades,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            avg_win=float(np.mean(wins)) if wins else 0.0,
            avg_loss=float(np.mean(losses)) if losses else 0.0,
            profit_factor=profit_factor,
            trades=[t.model_dump() for t in self.trades],
            equity_curve=[ep.model_dump() for ep in self.equity_curve],
            timeframe=self.config.timeframe,
            commission=self.config.commission,
            slippage_bps=self.config.slippage_bps,
            max_position_pct=self.config.max_position_pct,
            allow_short=self.config.allow_short,
            audit=self.audit,
        )

    def _risk_ratios(self) -> tuple:
        """Annualised Sharpe and Sortino from the per-bar equity curve.

        Annualised by the actual bar size. Using sqrt(252) on minute bars, as
        this engine previously did, inflates Sharpe by about twentyfold.
        """
        if len(self.equity_curve) < 2:
            return 0.0, 0.0

        equity = np.array([ep.equity for ep in self.equity_curve], dtype=float)
        if np.any(equity[:-1] == 0):
            return 0.0, 0.0

        returns = np.diff(equity) / equity[:-1]
        if returns.size == 0:
            return 0.0, 0.0

        scale = np.sqrt(periods_per_year(self.config.timeframe))
        mean = float(np.mean(returns))

        std = float(np.std(returns))
        sharpe = (mean / std) * scale if std > 0 else 0.0

        downside = returns[returns < 0]
        downside_std = float(np.std(downside)) if downside.size else 0.0
        sortino = (mean / downside_std) * scale if downside_std > 0 else 0.0

        return sharpe, sortino
