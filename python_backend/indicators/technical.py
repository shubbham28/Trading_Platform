"""
Technical Indicators Library
Provides various technical analysis indicators for trading strategies
"""
import pandas as pd
import numpy as np
from typing import Tuple


def calculate_sma(data: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average"""
    return data.rolling(window=period).mean()


def calculate_ema(data: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average"""
    return data.ewm(span=period, adjust=False).mean()


def calculate_rsi(data: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index
    
    Args:
        data: Price series
        period: RSI period (default: 14)
    
    Returns:
        RSI values as pandas Series
    """
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    data: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD (Moving Average Convergence Divergence)
    
    Args:
        data: Price series
        fast_period: Fast EMA period (default: 12)
        slow_period: Slow EMA period (default: 26)
        signal_period: Signal line period (default: 9)
    
    Returns:
        Tuple of (macd_line, signal_line, histogram)
    """
    fast_ema = calculate_ema(data, fast_period)
    slow_ema = calculate_ema(data, slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    data: pd.Series,
    period: int = 20,
    std_dev: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands
    
    Args:
        data: Price series
        period: Moving average period (default: 20)
        std_dev: Standard deviation multiplier (default: 2.0)
    
    Returns:
        Tuple of (upper_band, middle_band, lower_band)
    """
    middle_band = calculate_sma(data, period)
    std = data.rolling(window=period).std()
    upper_band = middle_band + (std * std_dev)
    lower_band = middle_band - (std * std_dev)
    
    return upper_band, middle_band, lower_band


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Calculate Volume Weighted Average Price
    
    Args:
        df: DataFrame with columns: high, low, close, volume
    
    Returns:
        VWAP as pandas Series
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
    return vwap


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range
    
    Args:
        df: DataFrame with columns: high, low, close
        period: ATR period (default: 14)
    
    Returns:
        ATR as pandas Series
    """
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    
    return atr


def calculate_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3
) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate Stochastic Oscillator
    
    Args:
        df: DataFrame with columns: high, low, close
        k_period: %K period (default: 14)
        d_period: %D period (default: 3)
    
    Returns:
        Tuple of (%K, %D)
    """
    lowest_low = df['low'].rolling(window=k_period).min()
    highest_high = df['high'].rolling(window=k_period).max()
    
    k_percent = 100 * ((df['close'] - lowest_low) / (highest_high - lowest_low))
    d_percent = k_percent.rolling(window=d_period).mean()
    
    return k_percent, d_percent


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all available indicators and add them to the DataFrame
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        DataFrame with all indicators added
    """
    result = df.copy()
    
    # Moving averages
    result['sma_10'] = calculate_sma(df['close'], 10)
    result['sma_20'] = calculate_sma(df['close'], 20)
    result['sma_50'] = calculate_sma(df['close'], 50)
    result['ema_12'] = calculate_ema(df['close'], 12)
    result['ema_26'] = calculate_ema(df['close'], 26)
    
    # RSI
    result['rsi'] = calculate_rsi(df['close'], 14)
    
    # MACD
    macd_line, signal_line, histogram = calculate_macd(df['close'])
    result['macd'] = macd_line
    result['macd_signal'] = signal_line
    result['macd_histogram'] = histogram
    
    # Bollinger Bands
    upper, middle, lower = calculate_bollinger_bands(df['close'])
    result['bb_upper'] = upper
    result['bb_middle'] = middle
    result['bb_lower'] = lower
    
    # VWAP (if volume exists)
    if 'volume' in df.columns:
        result['vwap'] = calculate_vwap(df)
    
    # ATR
    result['atr'] = calculate_atr(df, 14)
    
    # Stochastic
    k, d = calculate_stochastic(df, 14, 3)
    result['stoch_k'] = k
    result['stoch_d'] = d
    
    return result
