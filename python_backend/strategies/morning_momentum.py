"""
Morning Momentum Strategy
Buy stocks that gap up > 2% on high pre-market volume
Filters: RSI(5) < 70, volume ratio > 2× 20-day avg
Entry at open, exit before close or if trailing stop hits
"""
from typing import Dict, Any
import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal
from indicators.technical import calculate_rsi, calculate_sma


class MorningMomentumStrategy(BaseStrategy):
    """Morning Momentum Strategy for intraday trading"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.gap_threshold = self.parameters.get('gap_threshold', 2.0)  # % gap up
        self.rsi_period = self.parameters.get('rsi_period', 5)
        self.rsi_max = self.parameters.get('rsi_max', 70)
        self.volume_ratio_min = self.parameters.get('volume_ratio_min', 2.0)
        self.volume_period = self.parameters.get('volume_period', 20)
        self.trailing_stop_pct = self.parameters.get('trailing_stop_pct', 2.0)
        self.description = f"Morning Momentum (gap>{self.gap_threshold}%, RSI<{self.rsi_max}, vol>{self.volume_ratio_min}x)"
        
        # Track position state for trailing stop
        self.position_open = False
        self.highest_price = None
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on morning momentum
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need enough data for calculations
        if index < max(self.rsi_period + 1, self.volume_period):
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data for calculations',
                price=df.iloc[index]['close']
            )
        
        bar = df.iloc[index]
        prev_bar = df.iloc[index - 1]
        
        # Calculate gap percentage (open vs previous close)
        gap_pct = ((bar['open'] - prev_bar['close']) / prev_bar['close']) * 100
        
        # Calculate RSI
        rsi = calculate_rsi(df['close'], self.rsi_period)
        current_rsi = rsi.iloc[index]
        
        # Calculate volume ratio (current volume vs average)
        avg_volume = df['volume'].iloc[index - self.volume_period:index].mean()
        volume_ratio = bar['volume'] / avg_volume if avg_volume > 0 else 0
        
        # Check if this is near market open (first bars of the day)
        # For intraday data, we assume early bars are open periods
        is_market_open_period = True  # Simplified for now
        
        # Check if this is near market close
        # For exit logic, we check if it's one of the last bars
        is_market_close_period = index >= len(df) - 3
        
        # Entry Logic: Gap up with momentum and volume confirmation
        if not self.position_open and is_market_open_period:
            if (gap_pct >= self.gap_threshold and 
                current_rsi < self.rsi_max and 
                volume_ratio >= self.volume_ratio_min):
                
                self.position_open = True
                self.highest_price = bar['close']
                
                confidence = min(
                    (gap_pct / (self.gap_threshold * 2)) * 0.4 +
                    (volume_ratio / (self.volume_ratio_min * 2)) * 0.4 +
                    ((self.rsi_max - current_rsi) / self.rsi_max) * 0.2,
                    1.0
                )
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='buy',
                    confidence=confidence,
                    reason=f'Morning gap up: {gap_pct:.2f}% gap, RSI={current_rsi:.1f}, vol_ratio={volume_ratio:.1f}x',
                    price=bar['close']
                )
        
        # Exit Logic: Trailing stop or end of day
        if self.position_open:
            # Update highest price for trailing stop
            if bar['close'] > self.highest_price:
                self.highest_price = bar['close']
            
            # Check trailing stop
            trailing_stop_price = self.highest_price * (1 - self.trailing_stop_pct / 100)
            
            if bar['close'] <= trailing_stop_price or is_market_close_period:
                self.position_open = False
                self.highest_price = None
                
                reason = 'Trailing stop hit' if bar['close'] <= trailing_stop_price else 'End of day exit'
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=reason,
                    price=bar['close']
                )
        
        return Signal(
            timestamp=bar['timestamp'],
            action='hold',
            confidence=0.0,
            reason=f'Monitoring: gap={gap_pct:.2f}%, RSI={current_rsi:.1f}, vol_ratio={volume_ratio:.1f}x',
            price=bar['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
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
