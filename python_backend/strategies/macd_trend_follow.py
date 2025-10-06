"""
MACD Trend Following Strategy
Buy when MACD line crosses above signal line (bullish)
Sell when MACD line crosses below signal line (bearish)
"""
from typing import Dict, Any
import pandas as pd

from .base import BaseStrategy, Signal
from indicators.technical import calculate_macd


class MACDTrendFollowStrategy(BaseStrategy):
    """MACD Trend Following Strategy"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.fast_period = self.parameters.get('fast_period', 12)
        self.slow_period = self.parameters.get('slow_period', 26)
        self.signal_period = self.parameters.get('signal_period', 9)
        self.description = f"MACD Trend Follow ({self.fast_period}/{self.slow_period}/{self.signal_period})"
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on MACD crossover
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need enough data for MACD calculation
        min_required = self.slow_period + self.signal_period
        if index < min_required:
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data for MACD calculation',
                price=df.iloc[index]['close']
            )
        
        # Calculate MACD
        close_prices = df['close']
        macd_line, signal_line, histogram = calculate_macd(
            close_prices,
            self.fast_period,
            self.slow_period,
            self.signal_period
        )
        
        current_macd = macd_line.iloc[index]
        current_signal = signal_line.iloc[index]
        previous_macd = macd_line.iloc[index - 1]
        previous_signal = signal_line.iloc[index - 1]
        current_histogram = histogram.iloc[index]
        
        # Bullish crossover: MACD crosses above signal line
        if previous_macd <= previous_signal and current_macd > current_signal:
            confidence = min(abs(current_histogram) / abs(current_macd) if current_macd != 0 else 0.5, 1.0)
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='buy',
                confidence=confidence,
                reason=f'MACD bullish crossover: MACD line crossed above signal line (histogram: {current_histogram:.4f})',
                price=df.iloc[index]['close']
            )
        
        # Bearish crossover: MACD crosses below signal line
        if previous_macd >= previous_signal and current_macd < current_signal:
            confidence = min(abs(current_histogram) / abs(current_macd) if current_macd != 0 else 0.5, 1.0)
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='sell',
                confidence=confidence,
                reason=f'MACD bearish crossover: MACD line crossed below signal line (histogram: {current_histogram:.4f})',
                price=df.iloc[index]['close']
            )
        
        # Trend continuation signals based on histogram strength
        if current_histogram > 0 and current_macd > 0:
            reason = f'MACD bullish trend continues (histogram: {current_histogram:.4f})'
        elif current_histogram < 0 and current_macd < 0:
            reason = f'MACD bearish trend continues (histogram: {current_histogram:.4f})'
        else:
            reason = f'MACD neutral (histogram: {current_histogram:.4f})'
        
        return Signal(
            timestamp=df.iloc[index]['timestamp'],
            action='hold',
            confidence=0.0,
            reason=reason,
            price=df.iloc[index]['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
        fast_period = parameters.get('fast_period', 12)
        slow_period = parameters.get('slow_period', 26)
        signal_period = parameters.get('signal_period', 9)
        
        if fast_period >= slow_period:
            raise ValueError("Fast period must be less than slow period")
        if fast_period < 2 or slow_period < 2 or signal_period < 2:
            raise ValueError("All periods must be at least 2")
        
        return True
