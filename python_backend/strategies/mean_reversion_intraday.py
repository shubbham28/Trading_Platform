"""
Mean Reversion Intraday Strategy
Buy an oversold RSI reading confirmed by price at the lower Bollinger band
Exit on RSI recovery, target, stop, or the session close

The Bollinger confirmation is now an actual entry filter. Previously it only
adjusted the confidence score while the entry fired regardless, so the strategy
took every oversold reading despite documenting otherwise. Set
`require_bb_confirmation=False` to get the old, unfiltered behaviour explicitly.
"""
from typing import Any, Dict, Optional

import pandas as pd

from indicators.technical import calculate_bollinger_bands, calculate_rsi
from .base import BarContext, BaseStrategy, Position, Signal


class MeanReversionIntradayStrategy(BaseStrategy):
    """Mean Reversion Intraday Strategy"""

    def _initialize(self):
        self.rsi_period = self.parameters.get('rsi_period', 5)
        self.rsi_oversold = self.parameters.get('rsi_oversold', 25)
        self.rsi_target = self.parameters.get('rsi_target', 50)
        self.bb_period = self.parameters.get('bb_period', 20)
        self.bb_std = self.parameters.get('bb_std', 2.0)
        self.bb_tolerance_pct = self.parameters.get('bb_tolerance_pct', 1.0)
        self.require_bb_confirmation = self.parameters.get(
            'require_bb_confirmation', True
        )
        self.take_profit_pct = self.parameters.get('take_profit_pct', 2.0)
        self.stop_loss_pct = self.parameters.get('stop_loss_pct', 1.5)
        self.description = (
            f"Mean Reversion Intraday (RSI{self.rsi_period}<{self.rsi_oversold})"
        )

    def warmup_bars(self) -> int:
        return max(self.rsi_period + 2, self.bb_period + 1)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_rsi'] = calculate_rsi(df['close'], self.rsi_period)
        upper, middle, lower = calculate_bollinger_bands(
            df['close'], self.bb_period, self.bb_std
        )
        df['_bb_lower'] = lower
        df['_bb_middle'] = middle
        return df

    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        now = window.iloc[-1]
        close = float(now['close'])
        rsi = now['_rsi']

        if pd.isna(rsi) or pd.isna(now['_bb_lower']):
            return self.hold(window, ctx, 'Insufficient data for calculations')

        if position is not None:
            pnl_pct = position.unrealized_pct(close)

            if rsi >= self.rsi_target:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.8,
                    reason=f'RSI recovered to {rsi:.1f}: {pnl_pct:.2f}%',
                    price=close,
                )
            if pnl_pct >= self.take_profit_pct:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.9,
                    reason=f'Take-profit hit: {pnl_pct:.2f}%', price=close,
                )
            if pnl_pct <= -self.stop_loss_pct:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.9,
                    reason=f'Stop-loss hit: {pnl_pct:.2f}%', price=close,
                )
            if ctx.is_session_last_bar:
                return Signal(
                    timestamp=ctx.timestamp, action='sell', confidence=0.7,
                    reason=f'Flat by session close: {pnl_pct:.2f}%', price=close,
                )
            return self.hold(window, ctx, f'Holding: {pnl_pct:.2f}%')

        if ctx.is_session_last_bar:
            return self.hold(window, ctx, 'Session closing, no new entries')

        if rsi >= self.rsi_oversold:
            return self.hold(window, ctx, f'RSI not oversold: {rsi:.1f}')

        bb_limit = float(now['_bb_lower']) * (1 + self.bb_tolerance_pct / 100)
        near_lower_bb = close <= bb_limit
        if self.require_bb_confirmation and not near_lower_bb:
            return self.hold(
                window, ctx,
                f'Oversold RSI {rsi:.1f} but price above lower band',
            )

        confidence = min(
            0.5 + ((self.rsi_oversold - rsi) / self.rsi_oversold) * 0.5, 1.0
        )
        if near_lower_bb:
            confidence = min(confidence + 0.2, 1.0)

        return Signal(
            timestamp=ctx.timestamp,
            action='buy',
            confidence=float(confidence),
            reason=(
                f'Oversold signal: RSI={rsi:.1f}'
                + (', at lower band' if near_lower_bb else '')
            ),
            price=close,
        )

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        rsi_period = parameters.get('rsi_period', 5)
        rsi_oversold = parameters.get('rsi_oversold', 25)
        rsi_target = parameters.get('rsi_target', 50)
        bb_period = parameters.get('bb_period', 20)

        if rsi_period < 2:
            raise ValueError("RSI period must be at least 2")
        if rsi_oversold >= rsi_target:
            raise ValueError("RSI oversold must be less than RSI target")
        if bb_period < 2:
            raise ValueError("Bollinger period must be at least 2")

        return True
