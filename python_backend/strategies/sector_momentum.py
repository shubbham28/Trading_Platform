"""
Sector Momentum Strategy
Identifies top sectors (via ETFs) each morning
Picks top 3 stocks in leading sector by volume surge and RSI(14)
Enters on trend confirmation, exits before close
"""
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal
from indicators.technical import calculate_rsi, calculate_ema, calculate_sma


class SectorMomentumStrategy(BaseStrategy):
    """Sector Momentum Strategy for intraday trading"""
    
    def _initialize(self):
        """Initialize strategy parameters"""
        self.rsi_period = self.parameters.get('rsi_period', 14)
        self.rsi_min = self.parameters.get('rsi_min', 50)  # Bullish momentum threshold
        self.rsi_max = self.parameters.get('rsi_max', 75)  # Not overbought
        self.volume_surge_threshold = self.parameters.get('volume_surge_threshold', 2.0)
        self.ema_trend_period = self.parameters.get('ema_trend_period', 20)
        self.trailing_stop_pct = self.parameters.get('trailing_stop_pct', 2.5)
        self.description = f"Sector Momentum (RSI {self.rsi_min}-{self.rsi_max}, vol>{self.volume_surge_threshold}x)"
        
        # Track position state
        self.position_open = False
        self.entry_price: Optional[float] = None
        self.highest_price: Optional[float] = None
        self.sector_selected = False
    
    def _check_sector_leadership(self, df: pd.DataFrame, index: int) -> bool:
        """
        Check if stock is in leading sector (simplified version)
        In production, this would query sector ETF performance
        
        Args:
            df: Price data
            index: Current index
        
        Returns:
            True if in leading sector
        """
        # Simplified: Check if stock has strong relative performance
        # In production, you'd compare against sector ETFs
        if index < 20:
            return False
        
        # Check recent price momentum
        recent_return = (df.iloc[index]['close'] - df.iloc[index - 20]['close']) / df.iloc[index - 20]['close']
        return recent_return > 0.03  # 3% gain in recent period
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze data and generate signal based on sector momentum
        
        Args:
            df: DataFrame with OHLCV data
            index: Current bar index
        
        Returns:
            Trading signal
        """
        # Need enough data for calculations
        if index < max(self.rsi_period + 1, self.ema_trend_period):
            return Signal(
                timestamp=df.iloc[index]['timestamp'],
                action='hold',
                confidence=0.0,
                reason='Insufficient data for calculations',
                price=df.iloc[index]['close']
            )
        
        bar = df.iloc[index]
        
        # Calculate indicators
        rsi = calculate_rsi(df['close'], self.rsi_period)
        current_rsi = rsi.iloc[index]
        
        ema = calculate_ema(df['close'], self.ema_trend_period)
        current_ema = ema.iloc[index]
        
        # Calculate volume surge
        avg_volume = df['volume'].iloc[max(0, index - 20):index].mean()
        volume_ratio = bar['volume'] / avg_volume if avg_volume > 0 else 1.0
        
        # Check trend
        is_uptrend = bar['close'] > current_ema
        
        # Check sector leadership
        in_leading_sector = self._check_sector_leadership(df, index)
        
        # Check if near end of day
        is_closing_period = index >= len(df) - 3
        
        # Entry Logic: Sector leadership + volume surge + RSI momentum + uptrend
        if not self.position_open:
            if (in_leading_sector and 
                volume_ratio >= self.volume_surge_threshold and
                self.rsi_min <= current_rsi <= self.rsi_max and
                is_uptrend):
                
                self.position_open = True
                self.entry_price = bar['close']
                self.highest_price = bar['close']
                self.sector_selected = True
                
                confidence = min(
                    0.4 + (volume_ratio / (self.volume_surge_threshold * 2)) * 0.3 +
                    ((current_rsi - self.rsi_min) / (self.rsi_max - self.rsi_min)) * 0.3,
                    1.0
                )
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='buy',
                    confidence=confidence,
                    reason=f'Sector momentum: RSI={current_rsi:.1f}, vol={volume_ratio:.1f}x, leading sector',
                    price=bar['close']
                )
        
        # Exit Logic: Trailing stop or end of day
        if self.position_open and self.entry_price is not None:
            # Update highest price for trailing stop
            if bar['close'] > self.highest_price:
                self.highest_price = bar['close']
            
            pnl_pct = ((bar['close'] - self.entry_price) / self.entry_price) * 100
            
            # Check trailing stop
            trailing_stop_price = self.highest_price * (1 - self.trailing_stop_pct / 100)
            
            if bar['close'] <= trailing_stop_price:
                self.position_open = False
                self.entry_price = None
                self.highest_price = None
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.9,
                    reason=f'Trailing stop hit: {pnl_pct:.2f}%',
                    price=bar['close']
                )
            
            # Trend reversal (close below EMA)
            if bar['close'] < current_ema:
                self.position_open = False
                self.entry_price = None
                self.highest_price = None
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=f'Trend reversal: {pnl_pct:.2f}%',
                    price=bar['close']
                )
            
            # RSI overbought exit
            if current_rsi > 80:
                self.position_open = False
                self.entry_price = None
                self.highest_price = None
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=f'RSI overbought: {current_rsi:.1f}, PnL={pnl_pct:.2f}%',
                    price=bar['close']
                )
            
            # End of day
            if is_closing_period:
                self.position_open = False
                self.entry_price = None
                self.highest_price = None
                
                return Signal(
                    timestamp=bar['timestamp'],
                    action='sell',
                    confidence=0.8,
                    reason=f'End of day exit: {pnl_pct:.2f}%',
                    price=bar['close']
                )
        
        sector_status = "leading" if in_leading_sector else "lagging"
        return Signal(
            timestamp=bar['timestamp'],
            action='hold',
            confidence=0.0,
            reason=f'Monitoring: {sector_status} sector, RSI={current_rsi:.1f}, vol={volume_ratio:.1f}x',
            price=bar['close']
        )
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """Validate strategy parameters"""
        rsi_period = parameters.get('rsi_period', 14)
        rsi_min = parameters.get('rsi_min', 50)
        rsi_max = parameters.get('rsi_max', 75)
        volume_surge_threshold = parameters.get('volume_surge_threshold', 2.0)
        
        if rsi_period < 2:
            raise ValueError("RSI period must be at least 2")
        if rsi_min < 0 or rsi_min > 100:
            raise ValueError("RSI min must be between 0 and 100")
        if rsi_max < 0 or rsi_max > 100:
            raise ValueError("RSI max must be between 0 and 100")
        if rsi_min >= rsi_max:
            raise ValueError("RSI min must be less than RSI max")
        if volume_surge_threshold <= 0:
            raise ValueError("Volume surge threshold must be positive")
        
        return True
