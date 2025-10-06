"""
SMA Crossover Strategy
Buy when short-period SMA crosses above long-period SMA
Sell when short-period SMA crosses below long-period SMA
"""
from typing import Dict, Any
import pandas as pd
from datetime import datetime

from .base import BaseStrategy, Signal
from indicators.technical import calculate_sma


class SMACrossoverStrategy(BaseStrategy):
    """Simple Moving Average Crossover Strategy"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.short_period = self.parameters.get('short_period', 10)
        self.long_period = self.parameters.get('long_period', 30)
        self.description = f"SMA Crossover ({self.short_period}/{self.long_period})"
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on SMA crossover
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need enough data for both SMAs
        if index < self.long_period:
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data for analysis',
                price=df.iloc[index]['close']
            )
        
        # Calculate SMAs
        close_prices = df['close']
        short_sma = calculate_sma(close_prices, self.short_period)
        long_sma = calculate_sma(close_prices, self.long_period)
        
        current_short = short_sma.iloc[index]
        current_long = long_sma.iloc[index]
        previous_short = short_sma.iloc[index - 1]
        previous_long = long_sma.iloc[index - 1]
        
        # Check for crossover
        # Bullish crossover: short crosses above long
        if previous_short <= previous_long and current_short > current_long:
            confidence = min(abs(current_short - current_long) / current_long, 1.0)
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='buy',
                confidence=confidence,
                reason=f'SMA bullish crossover: {self.short_period}-period crossed above {self.long_period}-period',
                price=df.iloc[index]['close']
            )
        
        # Bearish crossover: short crosses below long
        if previous_short >= previous_long and current_short < current_long:
            confidence = min(abs(current_long - current_short) / current_long, 1.0)
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='sell',
                confidence=confidence,
                reason=f'SMA bearish crossover: {self.short_period}-period crossed below {self.long_period}-period',
                price=df.iloc[index]['close']
            )
        
        return Signal(
            timestamp=df.iloc[index]['timestamp'],
            action='hold',
            confidence=0.0,
            reason='No crossover detected',
            price=df.iloc[index]['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
        short_period = parameters.get('short_period', 10)
        long_period = parameters.get('long_period', 30)
        
        if short_period >= long_period:
            raise ValueError("Short period must be less than long period")
        if short_period < 2 or long_period < 2:
            raise ValueError("Periods must be at least 2")
        
        return True
