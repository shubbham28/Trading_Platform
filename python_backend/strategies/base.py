"""
Base Strategy Class
Provides abstract base class for all trading strategies
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
from pydantic import BaseModel


class Signal(BaseModel):
    """Trading signal"""
    timestamp: datetime
    action: str  # 'buy', 'sell', or 'hold'
    confidence: float  # 0.0 to 1.0
    reason: str
    price: Optional[float] = None
    quantity: Optional[int] = None


class Trade(BaseModel):
    """Executed trade"""
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    quantity: int
    side: str  # 'long' or 'short'
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    reason: str


class BaseStrategy(ABC):
    """Abstract base class for trading strategies"""
    
    def __init__(self, parameters: Optional[Dict[str, Any]] = None):
        """
        Initialize strategy with parameters
        
        Args:
            parameters: Dictionary of strategy-specific parameters
        """
        self.parameters = parameters or {}
        self.name = self.__class__.__name__
        self.description = self.__doc__ or "Trading strategy"
        self._initialize()
    
    def _initialize(self):
        """Initialize strategy-specific state"""
        pass
    
    @abstractmethod
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        """
        Analyze market data and generate trading signal
        
        Args:
            df: DataFrame with OHLCV data and indicators
            index: Current bar index
        
        Returns:
            Signal object with trading decision
        """
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get strategy information
        
        Returns:
            Dictionary with strategy name, description, and parameters
        """
        return {
            'name': self.name,
            'description': self.description,
            'parameters': self.parameters,
        }
    
    @staticmethod
    def validate_parameters(parameters: Dict[str, Any]) -> bool:
        """
        Validate strategy parameters
        
        Args:
            parameters: Dictionary of parameters to validate
        
        Returns:
            True if valid, raises ValueError otherwise
        """
        return True
