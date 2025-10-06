"""
RSI Mean Reversion Strategy
Buy when RSI indicates oversold condition (below oversold threshold)
Sell when RSI indicates overbought condition (above overbought threshold)
"""
from typing import Dict, Any
import pandas as pd

from .base import BaseStrategy, Signal
from indicators.technical import calculate_rsi


class RSIMeanReversionStrategy(BaseStrategy):
    """RSI Mean Reversion Strategy"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.period = self.parameters.get('period', 14)
        self.oversold = self.parameters.get('oversold', 30)
        self.overbought = self.parameters.get('overbought', 70)
        self.description = f"RSI Mean Reversion (period={self.period}, oversold={self.oversold}, overbought={self.overbought})"
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on RSI levels
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need enough data for RSI calculation
        if index < self.period + 1:
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data for RSI calculation',
                price=df.iloc[index]['close']
            )
        
        # Calculate RSI
        close_prices = df['close']
        rsi = calculate_rsi(close_prices, self.period)
        
        current_rsi = rsi.iloc[index]
        previous_rsi = rsi.iloc[index - 1]
        
        # Check for oversold condition (potential buy)
        if previous_rsi <= self.oversold and current_rsi > self.oversold:
            confidence = (self.oversold - previous_rsi) / self.oversold if previous_rsi < self.oversold else 0.5
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='buy',
                confidence=min(confidence, 1.0),
                reason=f'RSI oversold signal: RSI crossed above {self.oversold} (current: {current_rsi:.2f})',
                price=df.iloc[index]['close']
            )
        
        # Check for overbought condition (potential sell)
        if current_rsi > self.overbought:
            confidence = (current_rsi - self.overbought) / (100 - self.overbought)
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='sell',
                confidence=min(confidence, 1.0),
                reason=f'RSI overbought signal: RSI is {current_rsi:.2f} (threshold: {self.overbought})',
                price=df.iloc[index]['close']
            )
        
        return Signal(
            timestamp=df.iloc[index]['timestamp'],
            action='hold',
            confidence=0.0,
            reason=f'RSI neutral: {current_rsi:.2f}',
            price=df.iloc[index]['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
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
