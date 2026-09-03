"""
Relative-Strength Momentum Strategy
Buy a symbol showing sustained relative strength on a volume surge, in an
uptrend, with RSI in a momentum band but not overbought.
Exit on a trailing stop, RSI exhaustion, or the session close.

NAMING, HONESTLY. This was called a sector momentum strategy and its docstring
described ranking sector ETFs and picking the top three names in the leading
sector. It never did that. `_check_sector_leadership` compared a symbol against
its own price twenty bars earlier -- single-symbol momentum, no sectors involved.

Real sector rotation needs several symbols priced at the same instants, and the
engine feeds a strategy exactly one symbol. Rather than keep a name that
promises cross-sectional ranking, this is described as what it is. Cross-symbol
ranking is a genuine feature and belongs with multi-symbol support, not behind a
misleading method name.
"""
from typing import Any, Dict, Optional

import pandas as pd

from indicators.technical import calculate_ema, calculate_rsi
from .base import BarContext, BaseStrategy, Position, Signal


class SectorMomentumStrategy(BaseStrategy):
    """Relative-strength momentum strategy (single symbol)"""

    def _initialize(self):
        self.rsi_period = self.parameters.get('rsi_period', 14)
        self.rsi_min = self.parameters.get('rsi_min', 50)
        self.rsi_max = self.parameters.get('rsi_max', 75)
        self.volume_surge_threshold = self.parameters.get('volume_surge_threshold', 2.0)
        self.ema_trend_period = self.parameters.get('ema_trend_period', 20)
        self.trailing_stop_pct = self.parameters.get('trailing_stop_pct', 2.5)
        self.momentum_lookback = self.parameters.get('momentum_lookback', 20)
        self.momentum_min_pct = self.parameters.get('momentum_min_pct', 3.0)
        self.volume_period = self.parameters.get('volume_period', 20)
        self.description = (
            f"Relative-Strength Momentum (RSI {self.rsi_min}-{self.rsi_max}, "
            f"vol>{self.volume_surge_threshold}x)"
        )

    def warmup_bars(self) -> int:
        return max(
            self.rsi_period + 2,
            self.ema_trend_period + 1,
            self.momentum_lookback + 1,
            self.volume_period + 1,
        )

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_rsi'] = calculate_rsi(df['close'], self.rsi_period)
        df['_ema_trend'] = calculate_ema(df['close'], self.ema_trend_period)
        df['_avg_volume'] = (
            df['volume'].rolling(self.volume_period).mean().shift(1)
        )
        df['_momentum_pct'] = df['close'].pct_change(self.momentum_lookback) * 100
        return df

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
            rsi = now['_rsi']

            if close <= trailing_stop:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.85,
                    reason=f'Trailing stop hit: {pnl_pct:.2f}%', price=close,
                )
            if not pd.isna(rsi) and rsi > self.rsi_max:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.8,
                    reason=f'RSI exhaustion at {rsi:.1f}: {pnl_pct:.2f}%',
                    price=close,
                )
            if ctx.is_session_last_bar:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.7,
                    reason=f'Flat by session close: {pnl_pct:.2f}%', price=close,
                )
            return self.hold(window, ctx, f'Holding: {pnl_pct:.2f}%')

        rsi = now['_rsi']
        ema_trend = now['_ema_trend']
        avg_volume = now['_avg_volume']
        momentum_pct = now['_momentum_pct']

        if (
            pd.isna(rsi) or pd.isna(ema_trend)
            or pd.isna(avg_volume) or pd.isna(momentum_pct)
            or avg_volume <= 0
        ):
            return self.hold(window, ctx, 'Insufficient data for calculations')

        if ctx.is_session_last_bar:
            return self.hold(window, ctx, 'Session closing, no new entries')

        volume_ratio = float(now['volume']) / float(avg_volume)
        has_momentum = momentum_pct >= self.momentum_min_pct
        is_uptrend = close > ema_trend
        rsi_in_band = self.rsi_min <= rsi <= self.rsi_max
        volume_surging = volume_ratio >= self.volume_surge_threshold

        if has_momentum and is_uptrend and rsi_in_band and volume_surging:
            confidence = min(
                0.5
                + (volume_ratio / (self.volume_surge_threshold * 2)) * 0.3
                + ((rsi - self.rsi_min) / max(self.rsi_max - self.rsi_min, 1)) * 0.2,
                1.0,
            )
            return Signal(
                timestamp=ctx.timestamp,
                action='buy',
                confidence=float(confidence),
                reason=(
                    f'Momentum {momentum_pct:.1f}% over {self.momentum_lookback} bars, '
                    f'RSI={rsi:.1f}, vol_ratio={volume_ratio:.1f}x'
                ),
                price=close,
            )

        return self.hold(
            window, ctx,
            f'No setup: momentum={momentum_pct:.1f}%, RSI={rsi:.1f}, '
            f'vol_ratio={volume_ratio:.1f}x',
        )

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        rsi_min = parameters.get('rsi_min', 50)
        rsi_max = parameters.get('rsi_max', 75)
        volume_surge = parameters.get('volume_surge_threshold', 2.0)
        trailing_stop = parameters.get('trailing_stop_pct', 2.5)

        if rsi_min >= rsi_max:
            raise ValueError("RSI min must be less than RSI max")
        if volume_surge <= 0:
            raise ValueError("Volume surge threshold must be positive")
        if trailing_stop <= 0:
            raise ValueError("Trailing stop must be positive")

        return True
