"""
VWAP Mean Reversion Strategy
Buy dips below VWAP in uptrend (EMA20 > EMA50)
Sell rallies above VWAP in downtrend
Exit on mean reversion or before close
"""
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal
from indicators.technical import calculate_vwap, calculate_ema


class VWAPReversionStrategy(BaseStrategy):
    """VWAP Mean Reversion Strategy for intraday trading"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.ema_fast = self.parameters.get('ema_fast', 20)
        self.ema_slow = self.parameters.get('ema_slow', 50)
        self.vwap_deviation_pct = self.parameters.get('vwap_deviation_pct', 0.5)  # % below VWAP to buy
        self.take_profit_pct = self.parameters.get('take_profit_pct', 1.0)
        self.stop_loss_pct = self.parameters.get('stop_loss_pct', 1.5)
        self.description = f"VWAP Mean Reversion (EMA{self.ema_fast}/{self.ema_slow})"
        
        # Track position state
        self.position_open = False
        self.entry_price: Optional[float] = None
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on VWAP mean reversion
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need enough data for calculations
        if index < self.ema_slow + 1:
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data for calculations',
                price=df.iloc[index]['close']
            )
        
        bar = df.iloc[index]
        
        # Calculate VWAP
        # For intraday, VWAP should reset each day, but we'll calculate cumulatively here
        vwap = calculate_vwap(df.iloc[:index + 1])
        current_vwap = vwap.iloc[-1]
        
        # Calculate EMAs to determine trend
        ema_fast = calculate_ema(df['close'], self.ema_fast)
        ema_slow = calculate_ema(df['close'], self.ema_slow)
        
        current_ema_fast = ema_fast.iloc[index]
        current_ema_slow = ema_slow.iloc[index]
        
        # Determine trend
        is_uptrend = current_ema_fast > current_ema_slow
        is_downtrend = current_ema_fast < current_ema_slow
        
        # Calculate deviation from VWAP
        vwap_deviation_pct = ((bar['close'] - current_vwap) / current_vwap) * 100
        
        # Check if near end of day
        is_closing_period = index >= len(df) - 3
        
        # Entry Logic: Buy dips in uptrend, sell rallies in downtrend
        if not self.position_open:
            # Long entry: Price below VWAP in uptrend
            if is_uptrend and vwap_deviation_pct < -self.vwap_deviation_pct:
                self.position_open = True
                self.entry_price = bar['close']
                
                confidence = min(
                    0.5 + (abs(vwap_deviation_pct) / (self.vwap_deviation_pct * 2)) * 0.5,
                    1.0
                )
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='buy',
                    confidence=confidence,
                    reason=f'VWAP dip in uptrend: {vwap_deviation_pct:.2f}% below VWAP',
                    price=bar['close']
                )
        
        # Exit Logic: Mean reversion, stop-loss, take-profit, or end of day
        if self.position_open and self.entry_price is not None:
            pnl_pct = ((bar['close'] - self.entry_price) / self.entry_price) * 100
            
            # Mean reversion: price back to or above VWAP
            if bar['close'] >= current_vwap:
                self.position_open = False
                self.entry_price = None
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=f'Mean reversion to VWAP: {pnl_pct:.2f}%',
                    price=bar['close']
                )
            
            # Stop-loss
            stop_loss_price = self.entry_price * (1 - self.stop_loss_pct / 100)
            if bar['close'] <= stop_loss_price:
                self.position_open = False
                self.entry_price = None
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.9,
                    reason=f'Stop-loss hit: {pnl_pct:.2f}%',
                    price=bar['close']
                )
            
            # Take-profit
            take_profit_price = self.entry_price * (1 + self.take_profit_pct / 100)
            if bar['close'] >= take_profit_price:
                self.position_open = False
                self.entry_price = None
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.9,
                    reason=f'Take-profit hit: {pnl_pct:.2f}%',
                    price=bar['close']
                )
            
            # End of day
            if is_closing_period:
                self.position_open = False
                self.entry_price = None
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=f'End of day exit: {pnl_pct:.2f}%',
                    price=bar['close']
                )
        
        trend_str = "uptrend" if is_uptrend else "downtrend" if is_downtrend else "neutral"
        return Signal(
            timestamp=bar['timestamp'],
            action='hold',
            confidence=0.0,
            reason=f'Monitoring: {trend_str}, VWAP dev={vwap_deviation_pct:.2f}%',
            price=bar['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
        ema_fast = parameters.get('ema_fast', 20)
        ema_slow = parameters.get('ema_slow', 50)
        vwap_deviation_pct = parameters.get('vwap_deviation_pct', 0.5)
        
        if ema_fast < 2:
            raise ValueError("Fast EMA period must be at least 2")
        if ema_slow < 2:
            raise ValueError("Slow EMA period must be at least 2")
        if ema_fast >= ema_slow:
            raise ValueError("Fast EMA must be less than slow EMA")
        if vwap_deviation_pct <= 0:
            raise ValueError("VWAP deviation percentage must be positive")
        
        return True
