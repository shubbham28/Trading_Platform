"""
SMA Crossover Strategy
Buy when short-period SMA crosses above long-period SMA
Sell when short-period SMA crosses below long-period SMA
"""
from typing import Any, Dict, Optional

import pandas as pd

from indicators.technical import calculate_sma
from .base import BarContext, BaseStrategy, Position, Signal


class SMACrossoverStrategy(BaseStrategy):
    """Simple Moving Average Crossover Strategy"""

    def _initialize(self):
        self.short_period = self.parameters.get('short_period', 10)
        self.long_period = self.parameters.get('long_period', 30)
        self.description = f"SMA Crossover ({self.short_period}/{self.long_period})"

    def warmup_bars(self) -> int:
        # One extra bar so the previous-bar comparison that detects a crossing
        # has a defined value to read.
        return self.long_period + 1

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_sma_short'] = calculate_sma(df['close'], self.short_period)
        df['_sma_long'] = calculate_sma(df['close'], self.long_period)
        return df

    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        now, prev = window.iloc[-1], window.iloc[-2]

        short_now, long_now = now['_sma_short'], now['_sma_long']
        short_prev, long_prev = prev['_sma_short'], prev['_sma_long']

        if pd.isna(short_prev) or pd.isna(long_prev):
            return self.hold(window, ctx, 'Insufficient data for analysis')

        if short_prev <= long_prev and short_now > long_now:
            return Signal(
                timestamp=ctx.timestamp,
                action='buy',
                confidence=min(abs(short_now - long_now) / long_now, 1.0),
                reason=(
                    f'SMA bullish crossover: {self.short_period}-period crossed '
                    f'above {self.long_period}-period'
                ),
                price=float(now['close']),
            )

        if short_prev >= long_prev and short_now < long_now:
            return Signal(
                timestamp=ctx.timestamp,
                action='sell',
                confidence=min(abs(long_now - short_now) / long_now, 1.0),
                reason=(
                    f'SMA bearish crossover: {self.short_period}-period crossed '
                    f'below {self.long_period}-period'
                ),
                price=float(now['close']),
            )

        return self.hold(window, ctx, 'No crossover detected')

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        short_period = parameters.get('short_period', 10)
        long_period = parameters.get('long_period', 30)

        if short_period >= long_period:
            raise ValueError("Short period must be less than long period")
        if short_period < 2 or long_period < 2:
            raise ValueError("Periods must be at least 2")

        return True
