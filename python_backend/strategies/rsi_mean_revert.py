"""
RSI Mean Reversion Strategy
Buy when RSI recovers up through the oversold threshold
Sell when RSI indicates overbought
"""
from typing import Any, Dict, Optional

import pandas as pd

from indicators.technical import calculate_rsi
from .base import BarContext, BaseStrategy, Position, Signal


class RSIMeanReversionStrategy(BaseStrategy):
    """RSI Mean Reversion Strategy"""

    def _initialize(self):
        self.period = self.parameters.get('period', 14)
        self.oversold = self.parameters.get('oversold', 30)
        self.overbought = self.parameters.get('overbought', 70)
        self.description = (
            f"RSI Mean Reversion (period={self.period}, "
            f"oversold={self.oversold}, overbought={self.overbought})"
        )

    def warmup_bars(self) -> int:
        return self.period + 2

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_rsi'] = calculate_rsi(df['close'], self.period)
        return df

    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        now, prev = window.iloc[-1], window.iloc[-2]
        rsi_now, rsi_prev = now['_rsi'], prev['_rsi']

        if pd.isna(rsi_now) or pd.isna(rsi_prev):
            return self.hold(window, ctx, 'Insufficient data for RSI calculation')

        if rsi_prev <= self.oversold and rsi_now > self.oversold:
            confidence = (
                (self.oversold - rsi_prev) / self.oversold
                if rsi_prev < self.oversold else 0.5
            )
            return Signal(
                timestamp=ctx.timestamp,
                action='buy',
                confidence=min(float(confidence), 1.0),
                reason=(
                    f'RSI oversold signal: RSI crossed above {self.oversold} '
                    f'(current: {rsi_now:.2f})'
                ),
                price=float(now['close']),
            )

        if rsi_now > self.overbought:
            confidence = (rsi_now - self.overbought) / (100 - self.overbought)
            return Signal(
                timestamp=ctx.timestamp,
                action='sell',
                confidence=min(float(confidence), 1.0),
                reason=(
                    f'RSI overbought signal: RSI is {rsi_now:.2f} '
                    f'(threshold: {self.overbought})'
                ),
                price=float(now['close']),
            )

        return self.hold(window, ctx, f'RSI neutral: {rsi_now:.2f}')

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        period = parameters.get('period', 14)
        oversold = parameters.get('oversold', 30)
        overbought = parameters.get('overbought', 70)

        if period < 2:
            raise ValueError("Period must be at least 2")
        if oversold >= overbought:
            raise ValueError("Oversold threshold must be less than overbought threshold")
        if oversold < 0 or overbought > 100:
            raise ValueError("RSI thresholds must be between 0 and 100")

        return True
