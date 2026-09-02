"""
VWAP Mean Reversion Strategy
Buy dips below session VWAP while the trend is up (EMA fast > EMA slow)
Exit on reversion to VWAP, stop, target, or the session close
"""
from typing import Any, Dict, Optional

import pandas as pd

from indicators.technical import calculate_ema, calculate_session_vwap
from .base import BarContext, BaseStrategy, Position, Signal


class VWAPReversionStrategy(BaseStrategy):
    """VWAP Mean Reversion Strategy for intraday trading"""

    def _initialize(self):
        self.ema_fast = self.parameters.get('ema_fast', 20)
        self.ema_slow = self.parameters.get('ema_slow', 50)
        self.vwap_deviation_pct = self.parameters.get('vwap_deviation_pct', 0.5)
        self.take_profit_pct = self.parameters.get('take_profit_pct', 1.0)
        self.stop_loss_pct = self.parameters.get('stop_loss_pct', 1.5)
        self.description = f"VWAP Mean Reversion (EMA{self.ema_fast}/{self.ema_slow})"

    def warmup_bars(self) -> int:
        return self.ema_slow + 1

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Session-reset VWAP. The previous implementation accumulated from the
        # first row of the whole frame, so on a multi-day backtest it compared
        # price against a multi-day average that no venue quotes.
        df['_vwap'] = calculate_session_vwap(df)
        df['_ema_fast'] = calculate_ema(df['close'], self.ema_fast)
        df['_ema_slow'] = calculate_ema(df['close'], self.ema_slow)
        return df

    def analyze(
        self,
        window: pd.DataFrame,
        ctx: BarContext,
        position: Optional[Position],
    ) -> Signal:
        now = window.iloc[-1]
        vwap = now['_vwap']

        if pd.isna(vwap) or pd.isna(now['_ema_slow']):
            return self.hold(window, ctx, 'Insufficient data for calculations')

        close = float(now['close'])
        deviation_pct = ((close - vwap) / vwap) * 100

        if position is None:
            is_uptrend = now['_ema_fast'] > now['_ema_slow']
            # Do not open a position that the flatten-by-close rule below would
            # immediately shut on the same session.
            if ctx.is_session_last_bar:
                return self.hold(window, ctx, 'Session closing, no new entries')

            if is_uptrend and deviation_pct < -self.vwap_deviation_pct:
                confidence = min(
                    0.5 + (abs(deviation_pct) / (self.vwap_deviation_pct * 2)) * 0.5,
                    1.0,
                )
                return Signal(
                    timestamp=ctx.timestamp,
                    action='buy',
                    confidence=float(confidence),
                    reason=f'VWAP dip in uptrend: {deviation_pct:.2f}% below VWAP',
                    price=close,
                )
            return self.hold(
                window, ctx, f'No setup: {deviation_pct:.2f}% from VWAP'
            )

        pnl_pct = position.unrealized_pct(close)

        if close >= vwap:
            return Signal(
                timestamp=ctx.timestamp, action='sell', confidence=0.8,
                reason=f'Mean reversion to VWAP: {pnl_pct:.2f}%', price=close,
            )

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

    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        ema_fast = parameters.get('ema_fast', 20)
        ema_slow = parameters.get('ema_slow', 50)
        deviation = parameters.get('vwap_deviation_pct', 0.5)
        stop_loss = parameters.get('stop_loss_pct', 1.5)

        if ema_fast >= ema_slow:
            raise ValueError("Fast EMA period must be less than slow EMA period")
        if deviation <= 0:
            raise ValueError("VWAP deviation must be positive")
        if stop_loss <= 0:
            raise ValueError("Stop loss must be positive")

        return True
