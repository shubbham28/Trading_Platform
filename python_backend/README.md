# Python Backend - Trading Platform

Advanced technical indicator-based trading strategies and backtesting engine.

## 🐍 Overview

This Python backend service provides:
- Technical indicator calculations (SMA, EMA, RSI, MACD, Bollinger Bands, VWAP, ATR, Stochastic)
- Strategy execution engine with multiple built-in strategies
- Comprehensive backtesting with performance metrics
- RESTful API built with FastAPI

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- pip or poetry
- Alpaca API credentials

### Installation

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your Alpaca credentials
```

4. Run the server:
```bash
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

## 📚 API Documentation

Once running, visit:
- Interactive API docs: `http://localhost:8000/docs`
- Alternative docs: `http://localhost:8000/redoc`

### Key Endpoints

#### Get Available Indicators
```
GET /indicators
```
Returns list of all available technical indicators.

#### Calculate Indicators
```
POST /indicators/calculate
{
  "symbol": "AAPL",
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "timeframe": "1Day"
}
```

#### List Strategies
```
GET /strategy/list
```
Returns all available trading strategies.

#### Run Strategy
```
POST /strategy/run
{
  "symbol": "AAPL",
  "strategy_id": "sma_crossover",
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "parameters": {
    "short_period": 10,
    "long_period": 30
  },
  "timeframe": "1Day"
}
```

#### Run Backtest
```
POST /backtest/run
{
  "symbol": "AAPL",
  "strategy_id": "rsi_mean_revert",
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "initial_capital": 10000,
  "commission": 0.001,
  "parameters": {
    "period": 14,
    "oversold": 30,
    "overbought": 70
  },
  "timeframe": "1Day"
}
```

## 🧠 Available Strategies

### 1. SMA Crossover (`sma_crossover`)
Simple Moving Average crossover strategy.

**Parameters:**
- `short_period` (default: 10) - Short-term SMA period
- `long_period` (default: 30) - Long-term SMA period

**Logic:**
- Buy when short SMA crosses above long SMA
- Sell when short SMA crosses below long SMA

### 2. RSI Mean Reversion (`rsi_mean_revert`)
Relative Strength Index mean reversion strategy.

**Parameters:**
- `period` (default: 14) - RSI calculation period
- `oversold` (default: 30) - Oversold threshold
- `overbought` (default: 70) - Overbought threshold

**Logic:**
- Buy when RSI crosses above oversold level
- Sell when RSI is above overbought level

### 3. MACD Trend Following (`macd_trend_follow`)
MACD-based trend following strategy.

**Parameters:**
- `fast_period` (default: 12) - Fast EMA period
- `slow_period` (default: 26) - Slow EMA period
- `signal_period` (default: 9) - Signal line period

**Logic:**
- Buy when MACD line crosses above signal line
- Sell when MACD line crosses below signal line

## 📊 Technical Indicators

The following indicators are available:

| Indicator | Description | Parameters |
|-----------|-------------|------------|
| SMA | Simple Moving Average | period |
| EMA | Exponential Moving Average | period |
| RSI | Relative Strength Index | period |
| MACD | Moving Average Convergence Divergence | fast_period, slow_period, signal_period |
| Bollinger Bands | Volatility bands | period, std_dev |
| VWAP | Volume Weighted Average Price | - |
| ATR | Average True Range | period |
| Stochastic | Stochastic Oscillator | k_period, d_period |

## 🔧 Creating Custom Strategies

To create a custom strategy:

1. Create a new file in `strategies/` directory
2. Inherit from `BaseStrategy` class
3. Implement the `analyze()` method
4. Register strategy in `strategies/__init__.py`

Example:

```python
from strategies.base import BaseStrategy, Signal
import pandas as pd

class MyCustomStrategy(BaseStrategy):
    """My custom trading strategy"""
    
    def _initialize(self):
        self.my_param = self.parameters.get('my_param', 10)
    
    def analyze(self, df: pd.DataFrame, index: int) -> Signal:
        # Your logic here
        return Signal(
            timestamp=df.iloc[index]['timestamp'],
            action='buy',  # or 'sell' or 'hold'
            confidence=0.8,
            reason='My custom signal',
            price=df.iloc[index]['close']
        )
```

## 🎯 Backtest Metrics

The backtesting engine provides comprehensive metrics:

- **Total Return**: Absolute and percentage returns
- **Sharpe Ratio**: Risk-adjusted return metric
- **Sortino Ratio**: Downside risk-adjusted return
- **Max Drawdown**: Maximum peak-to-trough decline
- **Win Rate**: Percentage of profitable trades
- **Profit Factor**: Ratio of gross profits to gross losses
- **Trade Statistics**: Total, winning, and losing trades
- **Average Win/Loss**: Average profit per winning/losing trade
- **Equity Curve**: Complete equity progression over time

## 🐳 Docker Deployment

The Python backend is included in the main `docker-compose.yml`:

```bash
docker-compose up python-backend
```

Or run all services:
```bash
docker-compose up
```

## 🔌 Integration with Node.js Backend

The Node.js server proxies requests to the Python backend via `/api/python/*` endpoints:

- `/api/python/indicators` → Python `/indicators`
- `/api/python/strategies` → Python `/strategy/list`
- `/api/python/strategies/run` → Python `/strategy/run`
- `/api/python/backtest` → Python `/backtest/run`

## 📦 Project Structure

```
python_backend/
├── app/
│   ├── backtest.py        # Backtesting engine
│   └── data_fetcher.py    # Alpaca data integration
├── indicators/
│   ├── __init__.py
│   └── technical.py       # Technical indicator library
├── strategies/
│   ├── __init__.py
│   ├── base.py           # Base strategy class
│   ├── sma_crossover.py  # SMA crossover strategy
│   ├── rsi_mean_revert.py # RSI mean reversion strategy
│   └── macd_trend_follow.py # MACD trend following strategy
├── main.py               # FastAPI application
├── requirements.txt      # Python dependencies
├── Dockerfile           # Docker configuration
└── .env.example         # Environment variables template
```

## 🧪 Testing

Run tests (if implemented):
```bash
pytest
```

## ⚠️ Notes

- Default trading mode is **paper trading**
- All strategies use Alpaca API for historical data
- Commission defaults to 0 but can be configured
- Strategies are designed to be modular and extensible

## 📝 Future Enhancements

- [ ] Machine learning-based strategies
- [ ] Portfolio optimization
- [ ] Walk-forward analysis
- [ ] Monte Carlo simulation
- [ ] Multi-asset portfolio backtesting
- [ ] Real-time strategy execution
- [ ] WebSocket support for live updates
- [ ] Strategy parameter optimization
- [ ] Risk management modules

## 📄 License

MIT
