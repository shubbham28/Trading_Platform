# System Architecture: Intraday Trading Strategies

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend                                 │
│                         (main.py - Port 8000)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Strategy Endpoints                             │  │
│  │  • GET  /strategy/list                                           │  │
│  │  • GET  /strategy/{id}                                           │  │
│  │  • POST /strategy/run                                            │  │
│  │  • POST /backtest/run                                            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │              News Forward Testing Endpoints                       │  │
│  │  • POST /forward/news/signals    (generate from news)           │  │
│  │  • GET  /forward/news/signals    (retrieve saved)               │  │
│  │  • GET  /forward/news/results    (performance metrics)          │  │
│  │  • POST /forward/news/simulate   (simulate trades)              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
         ┌──────────▼─────────┐         ┌──────────▼──────────┐
         │  Strategy Engine   │         │  News Forward Tester│
         │  (strategies/)     │         │  (news_forward_     │
         │                    │         │   tester.py)        │
         │  ┌──────────────┐  │         │                     │
         │  │ Base Strategy│  │         │  ┌──────────────┐   │
         │  └──────┬───────┘  │         │  │ Sentiment    │   │
         │         │          │         │  │ Analysis     │   │
         │  ┌──────▼───────┐  │         │  │ • FinBERT   │   │
         │  │  5 Intraday  │  │         │  │ • DistilBERT│   │
         │  │  Strategies: │  │         │  │ • Keywords  │   │
         │  │              │  │         │  └──────────────┘   │
         │  │ 1. Morning   │  │         │                     │
         │  │    Momentum  │  │         │  ┌──────────────┐   │
         │  │ 2. Opening   │  │         │  │ Signal       │   │
         │  │    Range     │  │         │  │ Generation   │   │
         │  │    Breakout  │  │         │  └──────────────┘   │
         │  │ 3. VWAP      │  │         │                     │
         │  │    Reversion │  │         │  ┌──────────────┐   │
         │  │ 4. Mean      │  │         │  │ Forward Test │   │
         │  │    Reversion │  │         │  │ Simulation   │   │
         │  │    Intraday  │  │         │  └──────────────┘   │
         │  │ 5. Sector    │  │         │                     │
         │  │    Momentum  │  │         └─────────────────────┘
         │  └──────────────┘  │
         └────────────────────┘
                    │
         ┌──────────▼──────────┐
         │  Backtest Engine    │
         │  (app/backtest.py)  │
         │                     │
         │  • Trade Simulation │
         │  • Position Mgmt    │
         │  • P&L Calculation  │
         │  • Metrics:         │
         │    - Sharpe Ratio   │
         │    - Sortino Ratio  │
         │    - Max Drawdown   │
         │    - Win Rate       │
         │    - Profit Factor  │
         │  • Equity Curve     │
         └─────────────────────┘
                    │
         ┌──────────▼──────────┐
         │   Data Fetcher      │
         │  (app/data_fetcher) │
         │                     │
         │  • Alpaca API       │
         │  • Historical OHLCV │
         │  • Multiple         │
         │    Timeframes:      │
         │    - 1Min, 5Min     │
         │    - 15Min, 1Hour   │
         │    - 1Day           │
         └─────────────────────┘
                    │
         ┌──────────▼──────────┐
         │   Alpaca Market     │
         │   Data API          │
         │                     │
         │  • Live Market Data │
         │  • Historical Data  │
         │  • Stocks & Crypto  │
         └─────────────────────┘
```

## Data Flow

### 1. Strategy Execution Flow
```
User Request → FastAPI Endpoint → Data Fetcher → Alpaca API
                                        ↓
                                  OHLCV DataFrame
                                        ↓
                              Strategy.analyze()
                                        ↓
                                Trading Signals
                                        ↓
                              Response (JSON)
```

### 2. Backtesting Flow
```
Backtest Request → Config + Strategy → Data Fetcher
                                            ↓
                                      Historical Data
                                            ↓
                                    Backtest Engine
                                    ↓             ↓
                            Simulate Trades   Track Equity
                                    ↓             ↓
                            Trade Log     Equity Curve
                                    ↓             ↓
                              Calculate Metrics
                                        ↓
                                Backtest Result (JSON)
```

### 3. News Forward Testing Flow
```
News Headlines → Sentiment Analysis → Sentiment Scores
                                            ↓
                                  Fetch Market Data (Volume)
                                            ↓
                                  Generate Trading Signals
                                            ↓
                                  Rank by Confidence
                                            ↓
                                  Save Signals (JSON)
                                            ↓
                          ┌─────────────────┴─────────────┐
                          ↓                               ↓
                   Simulate Trades               Track Results
                          ↓                               ↓
                    P&L Calculation              Performance Metrics
                          ↓                               ↓
                    Forward Test Result (JSON)
```

## File Structure

```
Trading_Platform/
│
├── python_backend/
│   ├── main.py                    # FastAPI app with endpoints
│   ├── news_forward_tester.py     # News sentiment & forward testing
│   ├── strategy_demo.ipynb        # Interactive examples
│   ├── INTRADAY_STRATEGIES.md     # Documentation
│   │
│   ├── strategies/
│   │   ├── __init__.py           # Strategy registry
│   │   ├── base.py               # Base strategy interface
│   │   ├── morning_momentum.py   # Gap up strategy
│   │   ├── opening_range_breakout.py  # ORB strategy
│   │   ├── vwap_reversion.py     # VWAP mean reversion
│   │   ├── mean_reversion_intraday.py # RSI reversion
│   │   └── sector_momentum.py    # Sector rotation
│   │
│   ├── app/
│   │   ├── backtest.py           # Backtesting engine
│   │   └── data_fetcher.py       # Market data fetching
│   │
│   ├── indicators/
│   │   ├── technical.py          # Technical indicators
│   │   └── __init__.py
│   │
│   └── results/
│       └── news_signals/         # Saved signals & results
│           ├── signals_2024-01-15.json
│           └── forward_test_2024-01-15.json
│
└── IMPLEMENTATION_SUMMARY.md      # This overview
```

## Technology Stack

```
┌─────────────────────────────────────────┐
│          Python Backend                 │
├─────────────────────────────────────────┤
│ • FastAPI          (REST API)           │
│ • Uvicorn          (ASGI Server)        │
│ • Pydantic         (Validation)         │
│ • Pandas/NumPy     (Data Processing)    │
│ • Transformers     (Sentiment)          │
│ • PyTorch          (ML Backend)         │
│ • alpaca-py        (Market Data)        │
│ • pandas-ta        (Indicators)         │
└─────────────────────────────────────────┘
```

## Strategy Parameter Overview

| Strategy | Key Parameters | Entry | Exit |
|----------|----------------|-------|------|
| Morning Momentum | gap_threshold, rsi_max, volume_ratio | Gap >2%, RSI<70, Vol>2x | Trailing stop, EOD |
| Opening Range Breakout | range_period, stop_loss, take_profit | Break OR high | Stop/Target/EOD |
| VWAP Reversion | ema_fast, ema_slow, vwap_deviation | Price < VWAP in uptrend | Mean reversion |
| Mean Reversion Intraday | rsi_oversold, rsi_target | RSI < 25 | RSI recovery |
| Sector Momentum | rsi_min, rsi_max, volume_surge | Sector leader, Vol>2x | Trailing/RSI>80 |

## API Response Examples

### Strategy List Response
```json
{
  "strategies": [
    {
      "id": "morning_momentum",
      "name": "MorningMomentumStrategy",
      "description": "Morning Momentum (gap>2.0%, RSI<70, vol>2.0x)",
      "parameters": {}
    }
  ]
}
```

### Backtest Result Response
```json
{
  "strategy_id": "morning_momentum",
  "symbol": "AAPL",
  "initial_capital": 10000.0,
  "final_capital": 10523.45,
  "total_return": 523.45,
  "total_return_pct": 5.23,
  "sharpe_ratio": 1.85,
  "max_drawdown_pct": 3.2,
  "total_trades": 15,
  "win_rate": 66.7,
  "trades": [...],
  "equity_curve": [...]
}
```

### News Signal Response
```json
{
  "signals": [
    {
      "symbol": "AAPL",
      "action": "buy",
      "sentiment_score": 0.82,
      "sentiment_label": "positive",
      "confidence": 0.89,
      "news_count": 3,
      "volume_score": 2.3
    }
  ]
}
```

## Integration Points

### Frontend Integration
- React app can call REST endpoints
- Real-time strategy monitoring
- Backtest visualization
- News signal dashboard

### Database Integration
- Save backtest results to SQLite/Postgres
- Historical signal tracking
- Performance analytics

### Trading Integration
- Connect to Alpaca Trading API
- Execute live/paper trades
- Real-time position monitoring

## Monitoring & Logging

All components include:
- Error handling with detailed messages
- Progress logging for long operations
- JSON serialization for all results
- File-based persistence for signals

## Security Considerations

- API keys stored in environment variables
- CORS configured (update for production)
- Request validation via Pydantic
- No sensitive data in responses

## Performance Optimization

- Vectorized operations with Pandas/NumPy
- Efficient indicator calculations
- Cached sentiment models
- Minimal memory footprint for backtests

---

This architecture provides a scalable, maintainable foundation for intraday trading strategy development and evaluation.
