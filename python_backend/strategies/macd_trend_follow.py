"""
MACD Trend Following Strategy
Buy when MACD line crosses above signal line (bullish)
Sell when MACD line crosses below signal line (bearish)
"""
from typing import Any, Dict, Optional

import pandas as pd

from indicators.technical import calculate_macd
from .base import BarContext, BaseStrategy, Position, Signal


class MACDTrendFollowStrategy(BaseStrategy):
    """MACD Trend Following Strategy"""

    def _initialize(self):
        self.fast_period = self.parameters.get('fast_period', 12)
        self.slow_period = self.parameters.get('slow_period', 26)
        self.signal_period = self.parameters.get('signal_period', 9)
        self.description = (
            f"MACD Trend Follow ({self.fast_period}/{self.slow_period}/"
            f"{self.signal_period})"
        )

    def warmup_bars(self) -> int:
        return self.slow_period + self.signal_period + 1

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        macd_line, signal_line, histogram = calculate_macd(
            df['close'], self.fast_period, self.slow_period, self.signal_period
        )
        df['_macd'] = macd_line
        df['_macd_signal'] = signal_line
        df['_macd_hist'] = histogram
        return df

    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        now, prev = window.iloc[-1], window.iloc[-2]

        macd_now, signal_now = now['_macd'], now['_macd_signal']
        macd_prev, signal_prev = prev['_macd'], prev['_macd_signal']
        histogram = now['_macd_hist']

        if pd.isna(macd_prev) or pd.isna(signal_prev):
            return self.hold(window, ctx, 'Insufficient data for MACD calculation')

        confidence = min(
            abs(histogram) / abs(macd_now) if macd_now != 0 else 0.5, 1.0
        )

        if macd_prev <= signal_prev and macd_now > signal_now:
            return Signal(
                timestamp=ctx.timestamp,
                action='buy',
                confidence=float(confidence),
                reason=(
                    'MACD bullish crossover: MACD line crossed above signal line '
                    f'(histogram: {histogram:.4f})'
                ),
                price=float(now['close']),
            )

        if macd_prev >= signal_prev and macd_now < signal_now:
            return Signal(
                timestamp=ctx.timestamp,
                action='sell',
                confidence=float(confidence),
                reason=(
                    'MACD bearish crossover: MACD line crossed below signal line '
                    f'(histogram: {histogram:.4f})'
                ),
                price=float(now['close']),
            )

        if histogram > 0 and macd_now > 0:
            reason = f'MACD bullish trend continues (histogram: {histogram:.4f})'
        elif histogram < 0 and macd_now < 0:
            reason = f'MACD bearish trend continues (histogram: {histogram:.4f})'
        else:
            reason = f'MACD neutral (histogram: {histogram:.4f})'

        return self.hold(window, ctx, reason)

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        fast_period = parameters.get('fast_period', 12)
        slow_period = parameters.get('slow_period', 26)
        signal_period = parameters.get('signal_period', 9)

        if fast_period >= slow_period:
            raise ValueError("Fast period must be less than slow period")
        if fast_period < 2 or slow_period < 2 or signal_period < 2:
            raise ValueError("All periods must be at least 2")

        return True
