"""
Opening Range Breakout Strategy
Establish each session's opening range, then trade a break above it
Exit on stop, target, or the session close

The opening range is rebuilt every session from that session's own bars. The
earlier implementation used a one-shot `opening_range_set` flag and a global bar
index, so it computed a single range from the first thirty bars of the entire
dataset and reused it for every session afterwards -- on a three-month backtest,
day one's range priced sixty days of breakouts.
"""
from typing import Any, Dict, Optional

import pandas as pd

from .base import BarContext, BaseStrategy, Position, Signal


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Opening Range Breakout Strategy for intraday trading"""

    def _initialize(self):
        # Minutes after the bell that define the range. Named for what it is:
        # the previous parameter was documented as minutes and consumed as a
        # bar count, so its meaning silently changed with the timeframe.
        self.range_minutes = self.parameters.get('range_minutes', 30)
        self.volume_confirmation = self.parameters.get('volume_confirmation', True)
        self.volume_threshold = self.parameters.get('volume_threshold', 1.5)
        self.stop_loss_pct = self.parameters.get('stop_loss_pct', 1.5)
        self.take_profit_pct = self.parameters.get('take_profit_pct', 3.0)
        self.volume_period = self.parameters.get('volume_period', 20)
        self.description = f"Opening Range Breakout ({self.range_minutes}min range)"

    def warmup_bars(self) -> int:
        return self.volume_period + 1

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_avg_volume'] = (
            df['volume'].rolling(self.volume_period).mean().shift(1)
        )
        return df

    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        now = window.iloc[-1]
        close = float(now['close'])

        if not ctx.is_intraday:
            # An opening range needs intraday bars. Refusing loudly beats
            # producing a number from a definition that does not apply.
            return self.hold(
                window, ctx,
                'Opening range requires intraday bars; not applicable to this timeframe',
            )

        if position is not None:
            pnl_pct = position.unrealized_pct(close)

            if pnl_pct <= -self.stop_loss_pct:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.9,
                    reason=f'Stop-loss hit: {pnl_pct:.2f}%', price=close,
                )
            if pnl_pct >= self.take_profit_pct:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.9,
                    reason=f'Take-profit hit: {pnl_pct:.2f}%', price=close,
                )
            if ctx.is_session_last_bar:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.7,
                    reason=f'Flat by session close: {pnl_pct:.2f}%', price=close,
                )
            return self.hold(window, ctx, f'Holding: {pnl_pct:.2f}%')

        session = self.session_slice(window, ctx)
        minutes = ctx.minutes_since_open

        if minutes is None or minutes <= self.range_minutes:
            return self.hold(window, ctx, 'Establishing this session\'s opening range')

        # Bars belonging to the range: those within `range_minutes` of this
        # session's first bar. Anchoring on the session's own first timestamp
        # keeps the range per-session and avoids assuming the tape starts
        # exactly at the bell.
        session_ts = pd.to_datetime(session['timestamp'])
        offsets = (session_ts - session_ts.iloc[0]).dt.total_seconds() / 60.0
        range_bars = session[offsets <= self.range_minutes]
        if range_bars.empty:
            return self.hold(window, ctx, 'Opening range not established for this session')

        range_high = float(range_bars['high'].max())

        if ctx.is_session_last_bar:
            return self.hold(window, ctx, 'Session closing, no new entries')

        if close <= range_high:
            return self.hold(
                window, ctx, f'Inside opening range (high {range_high:.2f})'
            )

        avg_volume = now['_avg_volume']
        if pd.isna(avg_volume) or avg_volume <= 0:
            return self.hold(window, ctx, 'Insufficient volume history')

        volume_ratio = float(now['volume']) / float(avg_volume)
        if self.volume_confirmation and volume_ratio < self.volume_threshold:
            return self.hold(
                window, ctx,
                f'Breakout without volume confirmation ({volume_ratio:.1f}x)',
            )

        confidence = min(0.6 + (volume_ratio / (self.volume_threshold * 2)) * 0.4, 1.0)
        return Signal(
            timestamp=ctx.timestamp,
            action='buy',
            confidence=float(confidence),
            reason=(
                f'Breakout above session OR high {range_high:.2f}, '
                f'vol_ratio={volume_ratio:.1f}x'
            ),
            price=close,
        )

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        range_minutes = parameters.get('range_minutes', 30)
        volume_threshold = parameters.get('volume_threshold', 1.5)
        stop_loss_pct = parameters.get('stop_loss_pct', 1.5)
        take_profit_pct = parameters.get('take_profit_pct', 3.0)

        if range_minutes <= 0:
            raise ValueError("Range minutes must be positive")
        if volume_threshold <= 0:
            raise ValueError("Volume threshold must be positive")
        if stop_loss_pct <= 0:
            raise ValueError("Stop loss must be positive")
        if take_profit_pct <= 0:
            raise ValueError("Take profit must be positive")

        return True
