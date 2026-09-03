"""
Morning Momentum Strategy
Buy an overnight gap up on heavy volume, early in the session
Exit on a trailing stop or before the session close

The gap here is a real overnight gap: this session's opening price against the
previous session's closing price. The earlier implementation compared each bar's
open against the previous bar's close and set `is_market_open_period = True`
unconditionally, so on minute data it was testing one-minute gaps at any hour of
the day. That is not a morning-momentum strategy.
"""
from typing import Any, Dict, Optional

import pandas as pd

from indicators.technical import calculate_rsi
from .base import BarContext, BaseStrategy, Position, Signal


class MorningMomentumStrategy(BaseStrategy):
    """Morning Momentum Strategy for intraday trading"""

    def _initialize(self):
        self.gap_threshold = self.parameters.get('gap_threshold', 2.0)
        self.rsi_period = self.parameters.get('rsi_period', 5)
        self.rsi_max = self.parameters.get('rsi_max', 70)
        self.volume_ratio_min = self.parameters.get('volume_ratio_min', 2.0)
        self.volume_period = self.parameters.get('volume_period', 20)
        self.trailing_stop_pct = self.parameters.get('trailing_stop_pct', 2.0)
        # How long after the bell entries are still considered. Ignored on daily
        # bars, where the single bar is the whole session.
        self.entry_window_minutes = self.parameters.get('entry_window_minutes', 30)
        self.description = (
            f"Morning Momentum (gap>{self.gap_threshold}%, "
            f"RSI<{self.rsi_max}, vol>{self.volume_ratio_min}x)"
        )

    def warmup_bars(self) -> int:
        return max(self.rsi_period + 2, self.volume_period + 1)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_rsi'] = calculate_rsi(df['close'], self.rsi_period)
        # Trailing average excludes the current bar, so a volume spike is
        # measured against its own history rather than against itself.
        df['_avg_volume'] = (
            df['volume'].rolling(self.volume_period).mean().shift(1)
        )
        return df

    def _overnight_gap_pct(
        self, window: pd.DataFrame, ctx: BarContext
    ) -> Optional[float]:
        """This session's open against the previous session's close."""
        session_start = len(window) - 1 - ctx.session_bar_index
        if session_start <= 0:
            return None  # no previous session in view
        session_open = float(window.iloc[session_start]['open'])
        prev_close = float(window.iloc[session_start - 1]['close'])
        if prev_close == 0:
            return None
        return ((session_open - prev_close) / prev_close) * 100

    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        now = window.iloc[-1]
        close = float(now['close'])

        if position is not None:
            since_entry = self.bars_since_entry(window, position)
            high_water = float(since_entry['high'].max())
            trailing_stop = high_water * (1 - self.trailing_stop_pct / 100)
            pnl_pct = position.unrealized_pct(close)

            if close <= trailing_stop:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.8,
                    reason=f'Trailing stop hit: {pnl_pct:.2f}%', price=close,
                )
            if ctx.is_session_last_bar:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.7,
                    reason=f'Flat by session close: {pnl_pct:.2f}%', price=close,
                )
            return self.hold(window, ctx, f'Holding: {pnl_pct:.2f}%')

        gap_pct = self._overnight_gap_pct(window, ctx)
        if gap_pct is None:
            return self.hold(window, ctx, 'No previous session for gap measurement')

        in_entry_window = (
            not ctx.is_intraday
            or (ctx.minutes_since_open is not None
                and ctx.minutes_since_open <= self.entry_window_minutes)
        )
        if not in_entry_window:
            return self.hold(window, ctx, 'Past the morning entry window')
        if ctx.is_session_last_bar:
            return self.hold(window, ctx, 'Session closing, no new entries')

        rsi = now['_rsi']
        avg_volume = now['_avg_volume']
        if pd.isna(rsi) or pd.isna(avg_volume) or avg_volume <= 0:
            return self.hold(window, ctx, 'Insufficient data for calculations')

        volume_ratio = float(now['volume']) / float(avg_volume)

        if (
            gap_pct >= self.gap_threshold
            and rsi < self.rsi_max
            and volume_ratio >= self.volume_ratio_min
        ):
            confidence = min(
                (gap_pct / (self.gap_threshold * 2)) * 0.4
                + (volume_ratio / (self.volume_ratio_min * 2)) * 0.4
                + ((self.rsi_max - rsi) / self.rsi_max) * 0.2,
                1.0,
            )
            return Signal(
                timestamp=ctx.timestamp,
                action='buy',
                confidence=float(confidence),
                reason=(
                    f'Overnight gap up {gap_pct:.2f}%, RSI={rsi:.1f}, '
                    f'vol_ratio={volume_ratio:.1f}x'
                ),
                price=close,
            )

        return self.hold(
            window, ctx,
            f'Monitoring: gap={gap_pct:.2f}%, RSI={rsi:.1f}, '
            f'vol_ratio={volume_ratio:.1f}x',
        )

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        gap_threshold = parameters.get('gap_threshold', 2.0)
        rsi_period = parameters.get('rsi_period', 5)
        rsi_max = parameters.get('rsi_max', 70)
        volume_ratio_min = parameters.get('volume_ratio_min', 2.0)

        if gap_threshold <= 0:
            raise ValueError("Gap threshold must be positive")
        if rsi_period < 2:
            raise ValueError("RSI period must be at least 2")
        if rsi_max < 0 or rsi_max > 100:
            raise ValueError("RSI max must be between 0 and 100")
        if volume_ratio_min <= 0:
            raise ValueError("Volume ratio min must be positive")

        return True
