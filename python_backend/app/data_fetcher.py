"""
Data Fetcher
Fetches historical market data from Alpaca API
"""
import os
from datetime import datetime
from typing import Optional, List
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


class DataFetcher:
    """Fetches historical market data"""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        Initialize data fetcher
        
        Args:
            api_key: Alpaca API key (defaults to env var)
            api_secret: Alpaca API secret (defaults to env var)
        """
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.api_secret = api_secret or os.getenv('ALPACA_API_SECRET')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API credentials not provided")
        
        self.client = StockHistoricalDataClient(self.api_key, self.api_secret)
    
    def get_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = '1Day'
    ) -> pd.DataFrame:
        """
        Fetch historical bars from Alpaca
        
        Args:
            symbol: Stock symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            timeframe: Bar timeframe (1Min, 5Min, 15Min, 1Hour, 1Day, etc.)
        
        Returns:
            DataFrame with OHLCV data
        """
        # Parse timeframe
        tf = self._parse_timeframe(timeframe)
        
        # Create request
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=datetime.fromisoformat(start_date),
            end=datetime.fromisoformat(end_date)
        )
        
        # Fetch data
        bars = self.client.get_stock_bars(request_params)
        
        # Convert to DataFrame
        df = bars.df
        
        if df.empty:
            return df
        
        # Reset index and rename columns
        df = df.reset_index()
        
        # Rename columns to match expected format
        column_mapping = {
            'timestamp': 'timestamp',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume',
            'trade_count': 'trade_count',
            'vwap': 'vwap'
        }
        
        # Keep only relevant columns
        available_cols = [col for col in column_mapping.keys() if col in df.columns]
        df = df[available_cols]
        
        return df
    
    def _parse_timeframe(self, timeframe: str) -> TimeFrame:
        """
        Parse timeframe string to Alpaca TimeFrame
        
        Args:
            timeframe: Timeframe string (e.g., '1Day', '1Hour', '5Min')
        
        Returns:
            Alpaca TimeFrame object
        """
        timeframe_map = {
            '1Min': TimeFrame.Minute,
            '5Min': TimeFrame(5, TimeFrame.Unit.Minute),
            '15Min': TimeFrame(15, TimeFrame.Unit.Minute),
            '1Hour': TimeFrame.Hour,
            '1Day': TimeFrame.Day,
            '1Week': TimeFrame.Week,
            '1Month': TimeFrame.Month,
        }
        
        tf = timeframe_map.get(timeframe)
        if not tf:
            # Try to parse custom timeframe
            # Format: <number><unit> where unit is Min, Hour, Day, Week, Month
            import re
            match = re.match(r'(\d+)(Min|Hour|Day|Week|Month)', timeframe)
            if match:
                amount = int(match.group(1))
                unit_str = match.group(2)
                
                unit_map = {
                    'Min': TimeFrame.Unit.Minute,
                    'Hour': TimeFrame.Unit.Hour,
                    'Day': TimeFrame.Unit.Day,
                    'Week': TimeFrame.Unit.Week,
                    'Month': TimeFrame.Unit.Month,
                }
                
                unit = unit_map.get(unit_str)
                if unit:
                    return TimeFrame(amount, unit)
            
            # Default to 1 Day
            return TimeFrame.Day
        
        return tf
