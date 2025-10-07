# Intraday Trading Strategies

This document describes the intraday trading strategies implemented in the Trading Platform.

## Overview

Five intraday trading strategies have been added to the platform:

1. **Morning Momentum** - Trades gap-up stocks with volume confirmation
2. **Opening Range Breakout** - Trades breakouts from the first 30 minutes
3. **VWAP Mean Reversion** - Trades mean reversion around VWAP
4. **Mean Reversion Intraday** - RSI-based oversold/overbought reversals
5. **Sector Momentum** - Trades leading stocks in trending sectors

## Strategy Details

### 1. Morning Momentum Strategy

**File:** `strategies/morning_momentum.py`

**Concept:** Identifies stocks that gap up significantly at market open with high volume, indicating strong momentum.

**Parameters:**
- `gap_threshold` (default: 2.0) - Minimum gap percentage to trigger entry
- `rsi_period` (default: 5) - RSI calculation period
- `rsi_max` (default: 70) - Maximum RSI threshold (avoid overbought)
- `volume_ratio_min` (default: 2.0) - Minimum volume vs 20-day average
- `trailing_stop_pct` (default: 2.0) - Trailing stop loss percentage

**Entry Conditions:**
- Gap up > 2% from previous close
- RSI(5) < 70
- Volume > 2× 20-day average

**Exit Conditions:**
- Trailing stop (2% from highest price)
- End of day

### 2. Opening Range Breakout (ORB)

**File:** `strategies/opening_range_breakout.py`

**Concept:** Establishes the high/low range of the first 30 minutes and trades breakouts above the high.

**Parameters:**
- `range_period` (default: 30) - Number of bars for opening range
- `volume_confirmation` (default: True) - Require volume surge
- `volume_threshold` (default: 1.5) - Volume ratio for confirmation
- `stop_loss_pct` (default: 1.5) - Stop loss percentage
- `take_profit_pct` (default: 3.0) - Take profit percentage

**Entry Conditions:**
- Price breaks above opening range high
- Volume confirmation (optional)

**Exit Conditions:**
- Stop loss hit (1.5%)
- Take profit hit (3%)
- End of day

### 3. VWAP Mean Reversion

**File:** `strategies/vwap_reversion.py`

**Concept:** Trades mean reversion when price deviates from VWAP in trending markets.

**Parameters:**
- `ema_fast` (default: 20) - Fast EMA for trend
- `ema_slow` (default: 50) - Slow EMA for trend
- `vwap_deviation_pct` (default: 0.5) - Deviation from VWAP to trigger
- `take_profit_pct` (default: 1.0) - Take profit percentage
- `stop_loss_pct` (default: 1.5) - Stop loss percentage

**Entry Conditions:**
- Uptrend: EMA(20) > EMA(50)
- Price < VWAP by at least 0.5%

**Exit Conditions:**
- Price returns to VWAP
- Take profit or stop loss
- End of day

### 4. Mean Reversion Intraday

**File:** `strategies/mean_reversion_intraday.py`

**Concept:** Buys oversold conditions (RSI < 25) expecting quick bounce.

**Parameters:**
- `rsi_period` (default: 5) - RSI calculation period
- `rsi_oversold` (default: 25) - Oversold threshold
- `rsi_target` (default: 50) - Target RSI for exit
- `bb_period` (default: 20) - Bollinger Bands period
- `bb_std` (default: 2.0) - Bollinger Bands std deviation
- `take_profit_pct` (default: 2.0) - Take profit percentage
- `stop_loss_pct` (default: 1.5) - Stop loss percentage

**Entry Conditions:**
- RSI(5) < 25
- Price near lower Bollinger Band

**Exit Conditions:**
- RSI recovers to 50
- Price returns to BB middle
- Take profit or stop loss
- End of day

### 5. Sector Momentum

**File:** `strategies/sector_momentum.py`

**Concept:** Identifies and trades the strongest stocks in leading sectors.

**Parameters:**
- `rsi_period` (default: 14) - RSI calculation period
- `rsi_min` (default: 50) - Minimum RSI (momentum threshold)
- `rsi_max` (default: 75) - Maximum RSI (avoid overbought)
- `volume_surge_threshold` (default: 2.0) - Volume ratio requirement
- `ema_trend_period` (default: 20) - EMA for trend confirmation
- `trailing_stop_pct` (default: 2.5) - Trailing stop percentage

**Entry Conditions:**
- Stock in leading sector (relative performance > 3% in 20 bars)
- Volume > 2× average
- 50 < RSI(14) < 75
- Price > EMA(20)

**Exit Conditions:**
- Trailing stop (2.5%)
- Trend reversal (close below EMA)
- RSI > 80 (overbought)
- End of day

## Backtesting

All strategies can be backtested using the unified backtesting engine:

```python
from strategies import get_strategy
from app.backtest import BacktestEngine, BacktestConfig
from app.data_fetcher import DataFetcher

# Fetch data
data_fetcher = DataFetcher()
df = data_fetcher.get_bars('AAPL', '2024-01-01', '2024-01-31', '5Min')

# Configure backtest
config = BacktestConfig(
    symbol='AAPL',
    start_date='2024-01-01',
    end_date='2024-01-31',
    initial_capital=10000.0,
    commission=0.001,
    strategy_id='morning_momentum',
    parameters={}
)

# Run backtest
strategy = get_strategy('morning_momentum')
engine = BacktestEngine(config, strategy)
result = engine.run(df)

print(f"Total Return: {result.total_return_pct:.2f}%")
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown_pct:.2f}%")
```

## API Endpoints

### List All Strategies
```
GET /strategy/list
```

Returns all available strategies including the new intraday ones.

### Run Strategy
```
POST /strategy/run
{
  "symbol": "AAPL",
  "strategy_id": "morning_momentum",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "timeframe": "5Min",
  "parameters": {}
}
```

### Backtest Strategy
```
POST /backtest/run
{
  "symbol": "AAPL",
  "strategy_id": "opening_range_breakout",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "initial_capital": 10000.0,
  "commission": 0.001,
  "timeframe": "5Min",
  "parameters": {}
}
```

## News-Based Forward Tester

The news forward tester analyzes sentiment from news headlines and generates trading signals.

### Generate Signals from News
```
POST /forward/news/signals
{
  "news_items": [
    {
      "symbol": "AAPL",
      "headline": "Apple announces strong quarterly earnings",
      "timestamp": "2024-01-15T09:30:00"
    }
  ],
  "symbols": ["AAPL", "GOOGL", "MSFT"],
  "top_n": 5
}
```

### Get Latest Signals
```
GET /forward/news/signals?date=2024-01-15
```

### Get Forward Test Results
```
GET /forward/news/results
```

### Simulate Forward Test
```
POST /forward/news/simulate
{
  "news_items": [...],
  "symbols": ["AAPL", "GOOGL"],
  "top_n": 5
}
```

## Sentiment Analysis

The news forward tester uses:
1. **FinBERT** (primary) - Financial sentiment model
2. **DistilBERT** (fallback) - General sentiment model
3. **Keyword-based** (fallback) - Simple positive/negative keywords

Results are saved in `/results/news_signals/` directory.

## Performance Metrics

The backtesting engine calculates:
- **Total Return** - Absolute and percentage return
- **Sharpe Ratio** - Risk-adjusted return
- **Sortino Ratio** - Downside risk-adjusted return
- **Max Drawdown** - Largest peak-to-trough decline
- **Win Rate** - Percentage of profitable trades
- **Profit Factor** - Gross profit / gross loss
- **Average Win/Loss** - Average profit and loss per trade

## Example Notebook

See `strategy_demo.ipynb` for a complete walkthrough including:
- Loading and testing strategies
- Running backtests
- Visualizing equity curves
- Comparing strategy performance
- Using the news forward tester

## Best Practices

1. **Timeframe Selection**
   - Use 1-5 minute bars for scalping strategies
   - Use 5-15 minute bars for standard intraday
   - Use 30-60 minute bars for swing intraday

2. **Risk Management**
   - Always set stop losses
   - Use position sizing (don't risk > 2% per trade)
   - Exit all positions before market close

3. **Strategy Parameters**
   - Backtest different parameter combinations
   - Use walk-forward analysis
   - Monitor strategy performance over time

4. **Market Conditions**
   - Strategies perform differently in different markets
   - Morning Momentum works best in trending markets
   - Mean Reversion works best in ranging markets
   - Monitor volume and volatility

## Installation

Install additional dependencies for sentiment analysis:

```bash
pip install transformers torch sentencepiece
```

## Support

For questions or issues, please refer to the main README or open an issue on GitHub.
