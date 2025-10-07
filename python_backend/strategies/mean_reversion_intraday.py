"""
Mean Reversion Intraday Strategy
Enter long when RSI(5) < 25 and no negative news
Target small reversal before end of day
"""
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal
from indicators.technical import calculate_rsi, calculate_bollinger_bands


class MeanReversionIntradayStrategy(BaseStrategy):
    """Mean Reversion Intraday Strategy"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.rsi_period = self.parameters.get('rsi_period', 5)
        self.rsi_oversold = self.parameters.get('rsi_oversold', 25)
        self.rsi_target = self.parameters.get('rsi_target', 50)
        self.bb_period = self.parameters.get('bb_period', 20)
        self.bb_std = self.parameters.get('bb_std', 2.0)
        self.take_profit_pct = self.parameters.get('take_profit_pct', 2.0)
        self.stop_loss_pct = self.parameters.get('stop_loss_pct', 1.5)
        self.description = f"Mean Reversion Intraday (RSI{self.rsi_period}<{self.rsi_oversold})"
        
        # Track position state
        self.position_open = False
        self.entry_price: Optional[float] = None
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on mean reversion
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need enough data for calculations
        if index < max(self.rsi_period + 1, self.bb_period):
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data for calculations',
                price=df.iloc[index]['close']
            )
        
        bar = df.iloc[index]
        
        # Calculate RSI
        rsi = calculate_rsi(df['close'], self.rsi_period)
        current_rsi = rsi.iloc[index]
        
        # Calculate Bollinger Bands for additional confirmation
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(
            df['close'], self.bb_period, self.bb_std
        )
        current_bb_lower = bb_lower.iloc[index]
        current_bb_middle = bb_middle.iloc[index]
        
        # Check if near end of day
        is_closing_period = index >= len(df) - 3
        
        # Entry Logic: Oversold RSI and price near lower Bollinger Band
        if not self.position_open:
            # Check if RSI is oversold
            if current_rsi < self.rsi_oversold:
                # Additional confirmation: price near lower BB
                near_lower_bb = bar['close'] <= current_bb_lower * 1.01
                
                self.position_open = True
                self.entry_price = bar['close']
                
                # Confidence based on how oversold
                confidence = min(
                    0.5 + ((self.rsi_oversold - current_rsi) / self.rsi_oversold) * 0.5,
                    1.0
                )
                
                if near_lower_bb:
                    confidence = min(confidence + 0.2, 1.0)
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='buy',
                    confidence=confidence,
                    reason=f'Oversold signal: RSI={current_rsi:.1f}, near BB lower',
                    price=bar['close']
                )
        
        # Exit Logic: RSI recovery, take-profit, stop-loss, or end of day
        if self.position_open and self.entry_price is not None:
            pnl_pct = ((bar['close'] - self.entry_price) / self.entry_price) * 100
            
            # Mean reversion: RSI recovers to target level
            if current_rsi >= self.rsi_target:
                self.position_open = False
                self.entry_price = None
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=f'RSI reversion: RSI={current_rsi:.1f}, PnL={pnl_pct:.2f}%',
                    price=bar['close']
                )
            
            # Price back to BB middle
            if bar['close'] >= current_bb_middle:
                self.position_open = False
                self.entry_price = None
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=f'BB mean reversion: PnL={pnl_pct:.2f}%',
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
        
        return Signal(
            timestamp=bar['timestamp'],
            action='hold',
            confidence=0.0,
            reason=f'Monitoring: RSI={current_rsi:.1f}',
            price=bar['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
        rsi_period = parameters.get('rsi_period', 5)
        rsi_oversold = parameters.get('rsi_oversold', 25)
        rsi_target = parameters.get('rsi_target', 50)
        
        if rsi_period < 2:
            raise ValueError("RSI period must be at least 2")
        if rsi_oversold < 0 or rsi_oversold > 100:
            raise ValueError("RSI oversold must be between 0 and 100")
        if rsi_target < 0 or rsi_target > 100:
            raise ValueError("RSI target must be between 0 and 100")
        if rsi_oversold >= rsi_target:
            raise ValueError("RSI oversold must be less than RSI target")
        
        return True
