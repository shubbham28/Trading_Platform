"""
Opening Range Breakout Strategy
Identifies first 30-min high/low
Enters long when price breaks above high with volume confirmation
Exits on stop-loss or end of day
"""
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal
from indicators.technical import calculate_sma


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Opening Range Breakout Strategy for intraday trading"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.range_period = self.parameters.get('range_period', 30)  # minutes for opening range
        self.volume_confirmation = self.parameters.get('volume_confirmation', True)
        self.volume_threshold = self.parameters.get('volume_threshold', 1.5)  # vs avg volume
        self.stop_loss_pct = self.parameters.get('stop_loss_pct', 1.5)
        self.take_profit_pct = self.parameters.get('take_profit_pct', 3.0)
        self.description = f"Opening Range Breakout ({self.range_period}min range)"
        
        # Track opening range
        self.opening_range_high: Optional[float] = None
        self.opening_range_low: Optional[float] = None
        self.opening_range_set = False
        self.position_open = False
        self.entry_price: Optional[float] = None
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on opening range breakout
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need minimum data
        if index < 2:
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data',
                price=df.iloc[index]['close']
            )
        
        bar = df.iloc[index]
        
        # Determine if we're in the opening range period
        # For simplicity, assume first 'range_period' bars define the opening range
        # In production, you'd check actual timestamps
        is_opening_period = index < self.range_period
        is_closing_period = index >= len(df) - 3
        
        # Set opening range
        if is_opening_period:
            if not self.opening_range_set:
                # Calculate opening range from bars so far
                opening_bars = df.iloc[:index + 1]
                self.opening_range_high = opening_bars['high'].max()
                self.opening_range_low = opening_bars['low'].min()
            
            return Signal(
                timestamp=bar['timestamp'],
                action='hold',
                confidence=0.0,
                reason=f'Establishing opening range: H={self.opening_range_high:.2f}, L={self.opening_range_low:.2f}',
                price=bar['close']
            )
        
        # Finalize opening range after period ends
        if not self.opening_range_set:
            self.opening_range_set = True
            opening_bars = df.iloc[:self.range_period]
            self.opening_range_high = opening_bars['high'].max()
            self.opening_range_low = opening_bars['low'].min()
        
        # Calculate average volume for confirmation
        avg_volume = df['volume'].iloc[max(0, index - 20):index].mean()
        volume_ratio = bar['volume'] / avg_volume if avg_volume > 0 else 1.0
        
        # Entry Logic: Breakout above opening range high
        if not self.position_open and self.opening_range_high is not None:
            if bar['close'] > self.opening_range_high:
                # Check volume confirmation
                volume_confirmed = not self.volume_confirmation or volume_ratio >= self.volume_threshold
                
                if volume_confirmed:
                    self.position_open = True
                    self.entry_price = bar['close']
                    
                    breakout_strength = (bar['close'] - self.opening_range_high) / self.opening_range_high
                    confidence = min(
                        0.6 + (volume_ratio / (self.volume_threshold * 2)) * 0.4,
                        1.0
                    )
                    
                    return Signal(
                        timestamp=bar['timestamp'],
                        action='buy',
                        confidence=confidence,
                        reason=f'Breakout above OR high {self.opening_range_high:.2f}, vol_ratio={volume_ratio:.1f}x',
                        price=bar['close']
                    )
        
        # Exit Logic: Stop-loss, take-profit, or end of day
        if self.position_open and self.entry_price is not None:
            pnl_pct = ((bar['close'] - self.entry_price) / self.entry_price) * 100
            stop_loss_price = self.entry_price * (1 - self.stop_loss_pct / 100)
            take_profit_price = self.entry_price * (1 + self.take_profit_pct / 100)
            
            # Check exit conditions
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
            reason=f'Monitoring: OR H={self.opening_range_high:.2f}, L={self.opening_range_low:.2f}',
            price=bar['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
        range_period = parameters.get('range_period', 30)
        stop_loss_pct = parameters.get('stop_loss_pct', 1.5)
        take_profit_pct = parameters.get('take_profit_pct', 3.0)
        
        if range_period <= 0:
            raise ValueError("Range period must be positive")
        if stop_loss_pct <= 0:
            raise ValueError("Stop loss percentage must be positive")
        if take_profit_pct <= 0:
            raise ValueError("Take profit percentage must be positive")
        
        return True
