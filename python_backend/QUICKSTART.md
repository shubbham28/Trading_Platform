# 🚀 Python Backend Quick Start Guide

This guide will help you get the Python backend up and running quickly.

## 📋 Prerequisites

- Python 3.11 or higher
- pip package manager
- Alpaca API credentials (free paper trading account)

## ⚡ Quick Setup (5 minutes)

### 1. Navigate to Python Backend Directory

```bash
cd python_backend
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- FastAPI - Web framework
- Uvicorn - ASGI server
- Pandas & NumPy - Data processing
- Alpaca-py - Market data API
- Pydantic - Data validation

### 4. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and add your Alpaca credentials:

```env
ALPACA_API_KEY=your_key_here
ALPACA_API_SECRET=your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_MODE=paper
```

### 5. Run the Server

```bash
uvicorn main:app --reload --port 8000
```

The API will be available at:
- **API**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

## 🎯 Try It Out

### Option 1: Run Demo Script

```bash
python3 example_usage.py
```

This will:
- Calculate technical indicators on sample data
- List all available strategies
- Run backtests for each strategy
- Display comprehensive results

### Option 2: Test API with curl

#### List Available Strategies
```bash
curl http://localhost:8000/strategy/list
```

#### List Technical Indicators
```bash
curl http://localhost:8000/indicators
```

#### Run a Backtest
```bash
curl -X POST http://localhost:8000/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "strategy_id": "sma_crossover",
    "start_date": "2023-01-01",
    "end_date": "2023-12-31",
    "initial_capital": 10000,
    "parameters": {
      "short_period": 10,
      "long_period": 30
    }
  }'
```

### Option 3: Use Interactive API Docs

1. Open http://localhost:8000/docs in your browser
2. Try the endpoints directly from the browser
3. See request/response schemas
4. Test with your Alpaca credentials

## 🧪 Test with Sample Data

Create a test file `test_strategy.py`:

```python
import pandas as pd
import numpy as np
from strategies import SMACrossoverStrategy
from app.backtest import BacktestEngine, BacktestConfig

# Create sample data
dates = pd.date_range('2023-01-01', periods=100)
prices = 100 + np.cumsum(np.random.randn(100))

df = pd.DataFrame({
    'timestamp': dates,
    'open': prices,
    'high': prices * 1.01,
    'low': prices * 0.99,
    'close': prices,
    'volume': 1000
})

# Test strategy
strategy = SMACrossoverStrategy({'short_period': 5, 'long_period': 20})
config = BacktestConfig(
    symbol='TEST',
    start_date='2023-01-01',
    end_date='2023-04-10',
    initial_capital=10000,
    strategy_id='sma_crossover'
)

engine = BacktestEngine(config, strategy)
result = engine.run(df)

print(f"Return: {result.total_return_pct:.2f}%")
print(f"Trades: {result.total_trades}")
print(f"Win Rate: {result.win_rate:.2f}%")
```

Run it:
```bash
python3 test_strategy.py
```

## 🐳 Docker Quick Start

From the root directory:

```bash
docker-compose up python-backend
```

Or run all services:
```bash
docker-compose up
```

## 📊 Available Strategies

| Strategy | ID | Description |
|----------|----|----|
| SMA Crossover | `sma_crossover` | Buy when short SMA crosses above long SMA |
| RSI Mean Reversion | `rsi_mean_revert` | Buy on oversold, sell on overbought |
| MACD Trend Following | `macd_trend_follow` | Follow MACD crossover signals |

## 🔧 Common Issues

### Module Not Found Error

Make sure virtual environment is activated:
```bash
source venv/bin/activate
```

### Alpaca API Error

Check your credentials in `.env` file and ensure you're using paper trading credentials.

### Port Already in Use

Change the port:
```bash
uvicorn main:app --reload --port 8001
```

## 📚 Next Steps

1. **Explore the API**: Visit http://localhost:8000/docs
2. **Read Strategy Docs**: Check `strategies/*.py` files
3. **Create Custom Strategy**: See `README.md` for guide
4. **Integrate with Frontend**: Use `/api/python/*` endpoints from Node.js

## 🆘 Getting Help

- Check the main README: `python_backend/README.md`
- Review example: `example_usage.py`
- Check API docs: http://localhost:8000/docs

## 🎉 You're Ready!

The Python backend is now running and ready to:
- ✅ Calculate technical indicators
- ✅ Execute trading strategies
- ✅ Run comprehensive backtests
- ✅ Serve results via REST API

Happy trading! 📈
