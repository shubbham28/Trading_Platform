"""
Strategy contracts.

Two invariants make backtest behaviour and live behaviour the same algorithm:

  1. A strategy only ever receives `window` -- the bars up to and including the
     current one. Future bars are not merely off-limits, they are absent. So
     `len(window)` is the number of bars seen so far, which is what it also is
     live. Anything a strategy derives from the shape of its input is therefore
     causal by construction, not by discipline.

  2. A strategy holds no position state. The engine owns the position and passes
     it in. A strategy cannot desync from the engine because it has nothing to
     desync with.

Anything a strategy needs to know about the trading session -- how long until
the close, whether this is the first bar of the day -- arrives on `BarContext`,
derived from the exchange calendar rather than from the data. Deriving "is it
nearly the close?" from the data is how a backtest learns the future.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

import pandas as pd
from pydantic import BaseModel


class Signal(BaseModel):
    """A strategy's decision for one bar.

    `action` is interpreted against the current position by the engine:
      flat  + buy  -> open long        long  + sell -> close long
      flat  + sell -> open short       short + buy  -> close short
    A strategy therefore never needs to know whether it is opening or closing.
    """
    timestamp: datetime
    action: str  # 'buy', 'sell', or 'hold'
    confidence: float  # 0.0 to 1.0
    reason: str
    price: Optional[float] = None
    quantity: Optional[int] = None


class Position(BaseModel):
    """An open position, owned by the engine and handed to the strategy.

    `qty` is signed: positive is long, negative is short. A flat book is
    represented by `None` rather than by a zero-qty Position, so that
    `if position:` is unambiguous.
    """
    qty: int
    entry_price: float
    entry_time: datetime

    @property
    def is_long(self) -> bool:
        return self.qty > 0

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    def unrealized_pct(self, price: float) -> float:
        """Percentage move in the position's favour at `price`."""
        direction = 1.0 if self.is_long else -1.0
        return ((price - self.entry_price) / self.entry_price) * 100 * direction


class Trade(BaseModel):
    """A completed round trip, recorded by the engine."""
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    quantity: int
    side: str  # 'long' or 'short'
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    commission: float = 0.0
    reason: str
    # True when the engine closed this at the end of the data rather than
    # because the strategy asked. These are not strategy exits and should be
    # read separately when judging a strategy.
    forced_liquidation: bool = False


@dataclass(frozen=True)
class BarContext:
    """Calendar facts about the current bar.

    Every field here is computable from the current timestamp plus the exchange
    calendar, and none of it is computable only from knowing how much data
    follows. That is the whole point: a strategy asking "how close is the
    close?" gets a real answer live, not a reading of the dataset's length.

    A frozen dataclass rather than a pydantic model: one of these is built per
    bar, and per-bar validation is not worth the cost on minute data.
    """
    index: int                     # position in the full series
    timestamp: pd.Timestamp
    session_date: date
    session_bar_index: int         # 0 for the first bar of this session
    minutes_since_open: Optional[float]
    minutes_to_close: Optional[float]
    is_session_first_bar: bool
    is_session_last_bar: bool
    is_intraday: bool
    bar_minutes: Optional[int]     # None for daily and coarser


class BaseStrategy(ABC):
    """Abstract base for all strategies.

    Subclasses implement `analyze` and nothing else is required. Parameters
    arrive as a dict so a strategy instance is fully described by
    (class, parameters) -- which is what lets a bot be a config record rather
    than a code change.
    """

    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        self.parameters = parameters or {}
        self.name = self.__class__.__name__
        self.description = self.__doc__ or "Trading strategy"
        self._initialize()

    def _initialize(self):
        """Read parameters into attributes. Must not hold position state."""
        pass

    @abstractmethod
    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        """Decide what to do on the current bar.

        Args:
            window: OHLCV plus precomputed indicator columns, ending at the
                current bar. `window.iloc[-1]` is now. There is no later data.
            ctx: calendar facts about the current bar.
            position: the open position, or None when flat.

        Returns:
            A Signal. Return 'hold' when there is nothing to do.
        """
        raise NotImplementedError

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add this strategy's indicator columns, once, before the run starts.

        Two reasons this is a separate hook rather than work done inside
        `analyze`:

        Cost -- computing a 50-period EMA inside `analyze` recomputes it from
        scratch on every bar, which is quadratic. On a quarter of minute bars
        that is the difference between a second and several minutes.

        Verifiability -- a causal indicator has a testable property: its value
        at bar i does not depend on whether bars after i exist. Concentrating
        every indicator here gives the look-ahead test one place to check, and
        `test_no_lookahead.py` asserts exactly that for every registered
        strategy. Rolling, ewm, diff, shift and within-session cumsum all
        satisfy it. Anything centred, back-filled, or normalised against a
        full-series min/max/mean does not, and will fail the test.

        Must return a frame with the same index; add columns, do not reorder or
        drop rows.
        """
        return df

    # -- helpers available to every strategy -------------------------------

    @staticmethod
    def hold(window: pd.DataFrame, ctx: BarContext, reason: str) -> Signal:
        """A no-action signal. Common enough to be worth not retyping."""
        return Signal(
            timestamp=ctx.timestamp,
            action='hold',
            confidence=0.0,
            reason=reason,
            price=float(window.iloc[-1]['close']),
        )

    @staticmethod
    def session_slice(window: pd.DataFrame, ctx: BarContext) -> pd.DataFrame:
        """Just the bars belonging to the current trading session.

        The intraday strategies all need "today's bars so far" -- for an opening
        range, a session high, a gap against yesterday's close. Slicing by
        `session_bar_index` is O(1) and, like everything else here, cannot reach
        past the current bar. Doing this by global index instead is how the
        opening-range strategy ended up computing one range from the first
        thirty bars of the dataset and reusing it for every session after.
        """
        return window.iloc[-(ctx.session_bar_index + 1):]

    @staticmethod
    def bars_since_entry(window: pd.DataFrame, position: Position) -> pd.DataFrame:
        """Bars from the position's entry to now, inclusive.

        Lets a trailing stop be recomputed from the window instead of carried in
        an attribute. A high-water mark held on the strategy is state that can
        drift from the engine's view of the position; derived from the window it
        cannot.
        """
        return window[window['timestamp'] >= position.entry_time]

    def warmup_bars(self) -> int:
        """Bars needed before this strategy's indicators are meaningful.

        The engine skips `analyze` entirely below this count, so a strategy
        does not have to guard every access itself.
        """
        return 0

    def default_parameters(self) -> Dict[str, Any]:
        """The parameters this instance actually resolved to.

        `_initialize` reads each parameter with `.get(key, default)`, so a
        default-constructed strategy carries the real defaults as attributes
        while `self.parameters` stays empty. Without exposing these, a UI asking
        "what should I put here?" is told `{}` and the operator guesses.
        """
        skip = {'parameters', 'name', 'description'}
        return {
            key: value for key, value in vars(self).items()
            if not key.startswith('_')
            and key not in skip
            and isinstance(value, (int, float, str, bool))
        }

    def get_info(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'parameters': self.parameters,
        }

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Raise ValueError on invalid parameters. Return True otherwise."""
        return True
